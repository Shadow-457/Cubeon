/* Cubeon's browser wrapper around the MIT Cubiomes generator. */
#include "generator.h"
#include "finders.h"
#include "util.h"
#include <math.h>
#include <stdint.h>

static Generator generator;
static uint64_t world_seed;
static int biomes[256 * 256];
static int markers[1024 * 3];
static int marker_count;
static unsigned char colors[256][3];

int cb_init(int version, uint32_t low, uint32_t high, int dim, int flags) {
    const int versions[] = {MC_1_21_WD, MC_1_21_3, MC_1_21_1, MC_1_20_6, MC_1_19_4, MC_1_18_2};
    if (version < 0 || version > 5 || dim < -1 || dim > 1) return 0;
    world_seed = ((uint64_t)high << 32) | low;
    setupGenerator(&generator, versions[version], flags);
    applySeed(&generator, dim, world_seed);
    initBiomeColors(colors);
    return 1;
}
int *cb_map(int x, int z, int span, int resolution, int y) {
    if (resolution < 1 || resolution > 256 || span < 16 || span > 65536) return 0;
    for (int row = 0; row < resolution; row++) {
        for (int col = 0; col < resolution; col++) {
            int px = x + (int)((double)col * span / resolution);
            int pz = z + (int)((double)row * span / resolution);
            biomes[row * resolution + col] = getBiomeAt(&generator, 4,
                (int)floor(px / 4.0), (int)floor(y / 4.0), (int)floor(pz / 4.0));
        }
    }
    return biomes;
}
static void marker(int type, int x, int z) {
    if (marker_count == 1024) return;
    markers[marker_count * 3] = type;
    markers[marker_count * 3 + 1] = x;
    markers[marker_count * 3 + 2] = z;
    marker_count++;
}
int *cb_markers(int x, int z, int span) {
    marker_count = 0;
    const int types[] = {Village, Desert_Pyramid, Jungle_Temple, Swamp_Hut,
        Igloo, Ocean_Ruin, Shipwreck, Monument, Mansion, Outpost, Ruined_Portal,
        Ancient_City, Trail_Ruins, Trial_Chambers, Fortress, Bastion, End_City};
    for (unsigned i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        StructureConfig config;
        if (!getStructureConfig(types[i], generator.mc, &config) || config.dim != generator.dim) continue;
        int size = config.regionSize * 16;
        int minx = (int)floor((x - 32) / (double)size);
        int minz = (int)floor((z - 32) / (double)size);
        int maxx = (int)floor((x + span + 32) / (double)size);
        int maxz = (int)floor((z + span + 32) / (double)size);
        for (int rz = minz; rz <= maxz; rz++) for (int rx = minx; rx <= maxx; rx++) {
            Pos position;
            if (!getStructurePos(types[i], generator.mc, world_seed, rx, rz, &position)) continue;
            if (position.x < x || position.z < z || position.x >= x + span || position.z >= z + span) continue;
            if (!isViableStructurePos(types[i], &generator, position.x, position.z, 0)) continue;
            if (generator.dim == 0 && !isViableStructureTerrain(types[i], &generator, position.x, position.z)) continue;
            marker(types[i], position.x, position.z);
        }
    }
    if (generator.dim == 0) {
        StrongholdIter iter;
        initFirstStronghold(&iter, generator.mc, world_seed);
        for (int i = 0; i < 128; i++) {
            int remaining = nextStronghold(&iter, &generator);
            if (iter.pos.x >= x && iter.pos.z >= z && iter.pos.x < x + span && iter.pos.z < z + span) marker(100, iter.pos.x, iter.pos.z);
            if (!remaining) break;
        }
        Pos spawn = estimateSpawn(&generator, 0);
        marker(101, spawn.x, spawn.z);
    }
    return markers;
}
int cb_count(void) { return marker_count; }
const char *cb_biome_name(int id) { const char *name = biome2str(generator.mc, id); return name ? name : "unknown"; }
int cb_biome_color(int id) { if (id < 0 || id > 255) return 0x687565; return (colors[id][0] << 16) | (colors[id][1] << 8) | colors[id][2]; }
