import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {inflateSync} from 'node:zlib';

class Pixels {
  constructor(data, width, height) {
    if (typeof data === 'number') { height = width; width = data; data = new Uint8ClampedArray(width * height * 4); }
    this.width = width; this.height = height; this.data = data;
    assert.equal(data.length, width * height * 4);
  }
}
function image(width, height, pixel) {
  const result = new Pixels(width, height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) result.data.set(pixel(x, y), (y * width + x) * 4);
  return result;
}
function decodePNG(bytes) {
  const buffer = Buffer.from(bytes), parts = [];
  assert.deepEqual([...buffer.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  let width, height;
  for (let offset = 8; offset < buffer.length;) {
    const length = buffer.readUInt32BE(offset), type = buffer.toString('ascii', offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    let crc = 0xffffffff;
    for (const byte of buffer.subarray(offset + 4, offset + 8 + length)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
    }
    assert.equal((crc ^ 0xffffffff) >>> 0, buffer.readUInt32BE(offset + 8 + length), `${type} checksum`);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4);
      assert.deepEqual([...data.subarray(8)], [8, 6, 0, 0, 0]);
    }
    if (type === 'IDAT') parts.push(data);
    offset += length + 12;
  }
  const rows = inflateSync(Buffer.concat(parts)), result = new Pixels(width, height), stride = width * 4;
  assert.equal(rows.length, (stride + 1) * height);
  for (let y = 0; y < height; y++) {
    assert.equal(rows[y * (stride + 1)], 0);
    result.data.set(rows.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)), y * stride);
  }
  return result;
}
const urls = new Map();
class PNGImage {
  set src(url) {
    urls.get(url).arrayBuffer().then(bytes => {
      this.pixels = decodePNG(new Uint8Array(bytes));
      this.naturalWidth = this.pixels.width; this.naturalHeight = this.pixels.height;
      this.onload();
    }).catch(error => this.onerror(error));
  }
}
const window = {}, context = vm.createContext({
  window, self: window, ImageData: Pixels, Image: PNGImage, Blob, TextEncoder, TextDecoder,
  Uint8Array, Uint8ClampedArray, Uint32Array, Float32Array, DataView, ArrayBuffer,
  structuredClone, setTimeout, clearTimeout,
  URL: {createObjectURL(blob) { const url = `blob:test:${urls.size}`; urls.set(url, blob); return url; }, revokeObjectURL(url) { urls.delete(url); }},
  document: {getElementById() { return null; }, createElement(type) {
    assert.equal(type, 'canvas');
    let pixels;
    return {getContext() { return {drawImage(source) { pixels = source.pixels; }, getImageData() { return pixels; }}; }};
  }},
});
for (const name of ['texture-codec.js', 'texture-animation.js', 'vendor/fflate.js', 'texture-surface.js']) {
  vm.runInContext(fs.readFileSync(new URL('../' + name, import.meta.url), 'utf8'), context, {filename: name});
}
const TS = window.TextureSurface, codec = window.TextureCodec;
codec.png = TS.png;
window.fflate.zip = (files, options, done) => {
  try { done(null, window.fflate.zipSync(files, options)); } catch (error) { done(error); }
};
const settings = {version: 1, depth: 100, shine: 35, smooth: 0, invert: false, metal: false};
const source = image(4, 4, (x, y) => [x * 60, y * 60, 80, x || y ? 255 : 0]);
const original = [...source.data], flat = TS.generate(source, {...settings, depth: 0});
assert.deepEqual([...source.data], original, 'Generating depth must preserve painted pixels');
for (let i = 0; i < source.data.length; i += 4) {
  assert.deepEqual([...flat.normal.data.subarray(i, i + 4)], [128, 128, 255, 255], 'Zero depth is flat, including transparent edges');
  assert.deepEqual([...flat.material.data.subarray(i, i + 4)], [89, 10, 0, 255], 'LabPBR dielectric channels are non-emissive');
}
assert.deepEqual([...TS.generate(source, {...settings, shine: 80, metal: true}).material.data.subarray(0, 4)], [204, 230, 0, 255]);
assert.equal(TS.supported({width: 1024, height: 1024}), true);
assert.equal(TS.supported({width: 1024, height: 1025}), false);
assert.throws(() => TS.settings({...settings, height: {w: 1024, h: 1025, pixels: ''}}), /million pixels/);

const entry = {id: 'block/test', textureId: 'block/test', src: 'textures/block/test.png', n: 'Test', w: 4, h: 8,
  animation: {width: 4, height: 4, frames: [0, {index: 1, time: 5}]} };
entry.mcmeta = {animation: entry.animation};
const sheet = image(4, 8, (x, y) => [y < 4 ? 0 : 255, y < 4 ? 0 : 255, y < 4 ? 0 : 255, 255]);
const isolated = TS.generate(sheet, {...settings, smooth: 2}, entry);
for (let y = 0; y < 8; y++) for (let x = 0; x < 4; x++) {
  const offset = (y * 4 + x) * 4;
  assert.deepEqual([...isolated.normal.data.subarray(offset, offset + 4)], [128, 128, 255, y < 4 ? 0 : 255], 'Frame boundaries must not bleed');
}
const dataPixels = image(3, 1, x => [[17, 222, 91, 0], [127, 128, 255, 1], [127, 128, 255, 128]][x]);
assert.deepEqual([...decodePNG(await TS.png(dataPixels).arrayBuffer()).data], [...dataPixels.data], 'PNG export must preserve RGB at zero and low alpha');

const custom = image(4, 8, (x, y) => { const level = x * 10 + y * 30; return [level, level, level, 255]; });
const customSettings = {...settings, invert: true, smooth: 2, height: codec.encode(custom)};
const path = 'assets/minecraft/textures/block/test.png', heightPath = TS.heightPath(entry);
const exported = await TS.exportMaps(sheet, customSettings, entry, path);
assert.equal(exported.settings.heightFile, heightPath);
assert.equal(exported.settings.height, undefined);
assert.deepEqual([...decodePNG(exported.files[heightPath]).data], [...custom.data], 'Editable heights must export before invert/smoothing');
const importedMaps = await TS.importMaps({[entry.id]: exported.settings}, exported.files);
const expected = TS.generate(sheet, customSettings, entry), reopened = TS.generate(sheet, importedMaps[entry.id], entry);
assert.deepEqual([...reopened.height.data], [...expected.height.data], 'Reimport must apply invert and smoothing exactly once');
assert.deepEqual([...reopened.normal.data], [...expected.normal.data]);
assert.equal(urls.size, 0);

const modelPath = 'assets/minecraft/models/block/test.json', model = new TextEncoder().encode('{"parent":"block/cube_all"}');
const originalNormal = new Uint8Array(await TS.png(dataPixels).arrayBuffer()), originalMaterial = originalNormal.slice();
const originalFiles = {[path]: new Uint8Array(await TS.png(sheet).arrayBuffer()),
  [path.replace('.png', '_n.png')]: originalNormal, [path.replace('.png', '_s.png')]: originalMaterial,
  [path.replace('.png', '_n.png.mcmeta')]: new TextEncoder().encode('{"animation":{}}'), [modelPath]: model};
const assets = new Map([['original', originalFiles]]);
window.MinecraftTextures = {entries: [entry], resolve: id => id === entry.id ? entry : null};
window.LocalStore = {getFiles: async id => assets.get(id), putFiles: async (id, files) => assets.set(id, files), mode: () => 'indexedDB', flush: async () => {}};
window.BenchArchive = {read: async bytes => window.fflate.unzipSync(bytes)};
window.CB = {ready: Promise.resolve(), PL: {default: {}}, D: {set: {pal: 'default'}, projects: []}, bump() {}, save: async () => true, renderAll() {}, toast() {}};
window.Ed = {open: async () => {}};
vm.runInContext(fs.readFileSync(new URL('../resource-packs.js', import.meta.url), 'utf8'), context, {filename: 'resource-packs.js'});
const RP = window.ResourcePacks;
const project = {name: 'Depth test', type: 'pack', size: 16, pal: 'default', assetId: 'original', texture: entry.id,
  edits: {[entry.id]: codec.encode(sheet)}, surfaces: {[entry.id]: customSettings}};
const packed = await RP.buildZip(project), files = window.fflate.unzipSync(new Uint8Array(await packed.arrayBuffer()));
const details = JSON.parse(new TextDecoder().decode(files['.cubeon/project.json']));
assert.equal(details.surfaces[entry.id].heightFile, heightPath);
for (const suffix of ['_n.png', '_s.png']) {
  const mapPath = path.replace('.png', suffix);
  assert.deepEqual(JSON.parse(new TextDecoder().decode(files[mapPath + '.mcmeta'])), entry.mcmeta);
  assert.deepEqual([...decodePNG(files[mapPath]).data], [...(suffix === '_n.png' ? expected.normal : expected.material).data]);
}
assert.deepEqual([...files[modelPath]], [...model]);
assert.deepEqual([...originalFiles[path.replace('.png', '_n.png')]], [...originalNormal], 'Export must not mutate imported originals');
const importedPack = await RP.importFile(Object.assign(packed, {name: 'depth.zip'}));
assert.deepEqual([...importedPack.surfaceImported], [entry.id]);
assert.deepEqual([...importedPack.textures].map(row => row.id), [entry.id], 'Generated shader maps should stay out of the editable texture list');
assert.deepEqual([...TS.generate(sheet, importedPack.surfaces[entry.id], entry).height.data], [...expected.height.data]);

const preserved = window.fflate.unzipSync(new Uint8Array(await (await RP.buildZip({...project, edits: {}, surfaces: {}})).arrayBuffer()));
assert.deepEqual([...preserved[path.replace('.png', '_n.png')]], [...originalNormal], 'Removing new depth must retain unrelated original shader files');
assert.deepEqual([...preserved[path.replace('.png', '_s.png')]], [...originalMaterial]);
const removed = window.fflate.unzipSync(new Uint8Array(await (await RP.buildZip({...importedPack, surfaces: {}})).arrayBuffer()));
for (const suffix of ['_n.png', '_s.png', '_n.png.mcmeta', '_s.png.mcmeta']) assert.equal(removed[path.replace('.png', suffix)], undefined, 'Removing imported Bench depth must remove its owned maps');
assert.equal(removed[heightPath], undefined);
assert.deepEqual([...removed[path]], [...files[path]]);
assert.deepEqual([...removed[modelPath]], [...model]);
console.log('Depth generation, exact shader PNG channels, animation isolation, editable-height reimport and pack ownership passed.');
