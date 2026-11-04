fn main() {
    let root =
        std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("../..");
    let out_dir = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    cubeon_mod_api_gen::generate(&root, &out_dir, cubeon_mod_api_gen::Target::Render)
        .expect("generating native render mod API");
}
