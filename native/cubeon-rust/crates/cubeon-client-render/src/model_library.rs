//! Parsed resource models for one startup or resource-pack reload.
use crate::Result;
use cubeon_assets::{
    model::CuboidModel,
    resolve::{AssetReader, ModelLibrary},
};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

#[derive(Default)]
pub struct ParsedModels {
    models: BTreeMap<String, Arc<CuboidModel>>,
    root: PathBuf,
}
/// Asset files under a content root, for models that name a file (obj).
struct RootAssets(PathBuf);
impl AssetReader for RootAssets {
    fn read_text(&self, location: &str) -> Option<String> {
        let (namespace, path) = location.split_once(':')?;
        // Only a resource location's characters, and no `.`/`..` step: an
        // .obj's `mtllib` names its .mtl as raw text, so it must not reach a
        // file outside the content root (`../..:x` as a namespace would).
        let valid = |c: u8| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c);
        if !namespace.bytes().all(valid)
            || matches!(namespace, "" | "." | "..")
            || !path.bytes().all(|c| valid(c) || c == b'/')
            || path.split('/').any(|part| matches!(part, "" | "." | ".."))
        {
            return None;
        }
        cubeon_core::prepared_files::read_to_string(
            &self.0.join(format!("assets/{namespace}/{path}")),
        )
        .ok()
    }
}
impl ParsedModels {
    /// Every `models/**.json` of a namespace directory, by identifier.
    pub fn load(root: &Path) -> Self {
        let Ok(namespaces) = fs::read_dir(root.join("assets")) else {
            return Self {
                root: root.to_owned(),
                ..Self::default()
            };
        };
        // Listed first, then read and parsed at once: a content pack has tens
        // of thousands of models.
        let mut files = Vec::new();
        for ns in namespaces.flatten() {
            let namespace = ns.file_name().to_string_lossy().into_owned();
            let base = ns.path().join("models");
            let mut stack = vec![base.clone()];
            while let Some(dir) = stack.pop() {
                let Ok(entries) = fs::read_dir(&dir) else {
                    continue;
                };
                for e in entries.flatten() {
                    let path = e.path();
                    // The entry's own type saves a stat per file; a link
                    // (content roots link into the base) is followed.
                    let is_dir = match e.file_type() {
                        Ok(t) if !t.is_symlink() => t.is_dir(),
                        _ => path.is_dir(),
                    };
                    if is_dir {
                        stack.push(path);
                    } else if path.extension().is_some_and(|x| x == "json")
                        && let Ok(rel) = path.strip_prefix(&base)
                    {
                        let rel = rel.with_extension("").to_string_lossy().replace('\\', "/");
                        files.push((format!("{namespace}:{rel}"), path));
                    }
                }
            }
        }
        let parsed = crate::par::par_map(&files, |(_, path)| {
            let text = cubeon_core::prepared_files::read_to_string(path).ok()?;
            CuboidModel::from_json(&text).ok().map(Arc::new)
        });
        let models = files
            .into_iter()
            .zip(parsed)
            .filter_map(|((id, _), model)| Some((id, model?)))
            .collect();
        Self {
            models,
            root: root.to_owned(),
        }
    }

    /// Blocks require every referenced resource, including parents. Items instead
    /// skip broken resources and use the resolver's missing-model fallback.
    pub fn block_library(&self, root: &Path, pending: Vec<String>) -> Result<ModelLibrary> {
        self.block_models(root, pending, false)
    }
    /// [`Self::block_library`], but a model that does not read takes the
    /// built-in missing model, logged, as vanilla's model discovery does
    /// ("Missing block model"). Mods' content gets this; vanilla's resources
    /// always read.
    pub fn block_library_or_missing(
        &self,
        root: &Path,
        pending: Vec<String>,
    ) -> Result<ModelLibrary> {
        self.block_models(root, pending, true)
    }
    fn block_models(
        &self,
        root: &Path,
        mut pending: Vec<String>,
        or_missing: bool,
    ) -> Result<ModelLibrary> {
        let mut models = BTreeMap::new();
        let mut skipped = std::collections::BTreeSet::new();
        while let Some(name) = pending.pop() {
            if models.contains_key(&name) || skipped.contains(&name) {
                continue;
            }
            let model = match self.models.get(&name) {
                Some(model) => Arc::clone(model),
                None => {
                    let read = || -> Result<CuboidModel> {
                        let (namespace, path) =
                            name.split_once(':').ok_or("invalid model identifier")?;
                        let text = cubeon_core::prepared_files::read_to_string(
                            &root.join(format!("assets/{namespace}/models/{path}.json")),
                        )?;
                        Ok(CuboidModel::from_json(&text)?)
                    };
                    match read() {
                        Ok(model) => Arc::new(model),
                        Err(e) if or_missing => {
                            log::warn!("Cubeon: missing block model {name}: {e}");
                            skipped.insert(name);
                            continue;
                        }
                        Err(e) => return Err(e),
                    }
                }
            };
            pending.extend(model.referenced_models());
            models.insert(name, model);
        }
        Ok(ModelLibrary::from_shared(models)?.with_assets(Arc::new(RootAssets(root.to_owned()))))
    }
    pub fn into_item_library(self) -> std::result::Result<Arc<ModelLibrary>, String> {
        let root = self.root;
        ModelLibrary::with_shared_item_generator(self.models)
            .map(|library| Arc::new(library.with_assets(Arc::new(RootAssets(root)))))
            .map_err(|e| format!("item models: {e:?}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cubeon_assets::resolve::{GENERATED_MODEL, MISSING_MODEL};

    struct Fixture(std::path::PathBuf);
    impl Fixture {
        fn write(&self, name: &str, json: &str) {
            let (namespace, path) = name.split_once(':').unwrap();
            let path = self
                .0
                .join(format!("assets/{namespace}/models/{path}.json"));
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, json).unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn shared_views_preserve_resolution_errors_builtins_and_reload() -> Result<()> {
        let fixture = Fixture(
            std::env::temp_dir().join(format!("cubeon-shared-models-{}", std::process::id())),
        );
        fixture.write("cubeon:parent", r##"{"textures":{"side":"#all","all":"block/stone"},"elements":[{"from":[0,0,0],"to":[16,8,16],"faces":{"up":{"texture":"#side"}}}]}"##);
        fixture.write("cubeon:nested/child", r#"{"parent":"cubeon:parent","textures":{"all":"block/glass"},"display":{"gui":{"rotation":[30,45,0]}}}"#);
        fixture.write("cubeon:broken", "{");
        fixture.write("cubeon:dangling", r#"{"parent":"cubeon:absent"}"#);
        fixture.write("cubeon:a", r#"{"parent":"cubeon:b"}"#);
        fixture.write("cubeon:b", r#"{"parent":"cubeon:a"}"#);
        fixture.write(
            GENERATED_MODEL,
            r#"{"elements":[{"from":[0,0,0],"to":[1,1,1],"faces":{"up":{"texture":"particle"}}}],"gui_light":"side"}"#,
        );
        fixture.write(MISSING_MODEL, r#"{"elements":[]}"#);
        let parsed = ParsedModels::load(&fixture.0);
        let direct = ParsedModels::default();
        let names = vec![
            "cubeon:nested/child".into(),
            GENERATED_MODEL.into(),
            MISSING_MODEL.into(),
            "cubeon:a".into(),
        ];
        let old = direct.block_library(&fixture.0, names.clone())?;
        let shared = parsed.block_library(&fixture.0, names)?;
        for name in ["cubeon:nested/child", GENERATED_MODEL, MISSING_MODEL] {
            assert_eq!(
                format!("{:?}", old.resolve(name)?),
                format!("{:?}", shared.resolve(name)?)
            );
        }
        assert!(shared.resolve("cubeon:a").is_err());
        for name in ["cubeon:broken", "cubeon:absent", "cubeon:dangling"] {
            let load = |models: &ParsedModels| {
                models
                    .block_library(&fixture.0, vec![name.into()])
                    .err()
                    .unwrap()
                    .to_string()
            };
            assert_eq!(load(&direct), load(&parsed));
            // Mods' content: vanilla's missing model instead of an error.
            let lenient = parsed.block_library_or_missing(&fixture.0, vec![name.into()])?;
            assert_eq!(
                format!("{:?}", lenient.resolve(name)?.elements()),
                format!("{:?}", lenient.resolve(MISSING_MODEL)?.elements()),
                "{name}"
            );
        }
        let items = parsed.into_item_library()?;
        let block = shared.resolve("cubeon:nested/child")?;
        let item = items.resolve("cubeon:nested/child")?;
        assert!(std::ptr::eq(
            block.elements().as_ptr(),
            item.elements().as_ptr()
        ));
        assert_eq!(
            item.material("side")?.unwrap().sprite,
            "minecraft:block/glass"
        );
        assert_eq!(shared.resolve(GENERATED_MODEL)?.elements().len(), 1);
        assert!(items.resolve(GENERATED_MODEL)?.elements().is_empty());
        assert!(items.resolve(GENERATED_MODEL)?.uses_item_generator());
        for name in [
            "cubeon:broken",
            "cubeon:absent",
            "cubeon:dangling",
            MISSING_MODEL,
        ] {
            assert_eq!(items.resolve(name)?.elements().len(), 1);
        }
        assert!(items.resolve("cubeon:a").is_err());
        fixture.write("cubeon:parent", r#"{"elements":[]}"#);
        let reloaded = ParsedModels::load(&fixture.0).into_item_library()?;
        assert!(
            reloaded
                .resolve("cubeon:nested/child")?
                .elements()
                .is_empty()
        );
        assert_eq!(items.resolve("cubeon:nested/child")?.elements().len(), 1);
        // An unrelated bad item identifier must not make block preparation fail
        // (which would trigger resource-pack rollback at a different stage).
        fixture.write("cubeon:INVALID", "{}");
        let parsed = ParsedModels::load(&fixture.0);
        assert!(
            parsed
                .block_library(&fixture.0, vec!["cubeon:nested/child".into()])
                .is_ok()
        );
        assert!(parsed.into_item_library().is_err());
        Ok(())
    }

    /// An .obj's `mtllib` is raw text: no namespace or path step reaches a
    /// file outside the content root.
    #[test]
    fn root_assets_stay_inside_the_content_root() {
        let root = std::env::temp_dir().join(format!("cubeon-root-assets-{}", std::process::id()));
        let inside = root.join("content");
        fs::create_dir_all(inside.join("assets/m/models")).unwrap();
        fs::write(inside.join("assets/m/models/a.mtl"), "newmtl a").unwrap();
        fs::write(root.join("secret.mtl"), "newmtl secret").unwrap();
        let assets = RootAssets(inside);
        assert_eq!(
            assets.read_text("m:models/a.mtl").as_deref(),
            Some("newmtl a")
        );
        for escape in [
            "../..:secret.mtl",
            "..:../secret.mtl",
            "m:../../../secret.mtl",
            "m:models/./a.mtl",
            "M:models/a.mtl",
            ":models/a.mtl",
        ] {
            assert_eq!(assets.read_text(escape), None, "{escape}");
        }
        fs::remove_dir_all(&root).unwrap();
    }
}
