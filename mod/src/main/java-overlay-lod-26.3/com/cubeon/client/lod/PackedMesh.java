package com.cubeon.client.lod;

import com.cubeon.client.lod.core.*;
import java.nio.*;
import java.util.*;

/** Baked off-thread. GPU faces use one compact record instead of six expanded CPU vertices. */
public record PackedMesh(TilePlan.Key key, byte[] solid, byte[] fluid, int solidCount, int fluidCount,
                         boolean gpu, int minY, int maxY, long stamp) {
    public static final int STRIDE = 64;
    private static final int[] CORNERS = {0, 1, 2, 0, 2, 3};
    public long bytes() { return 128L + solid.length + fluid.length; }
    public static PackedMesh pack(TileMesh mesh, boolean gpu, TextureCatalog catalog, long stamp, long limit) {
        int solid = 0, fluid = 0;
        for (var face : mesh.faces()) {
            if (catalog.get(face.material().state(), face.direction()) == null) return null;
            if ((face.material().flags() & Terrain.FLUID) != 0) fluid++; else solid++;
        }
        int multiplier = gpu ? 1 : 6;
        long size = (long)(solid + fluid) * STRIDE * multiplier;
        if (size > limit || size > Integer.MAX_VALUE) return null;
        var a = ByteBuffer.allocate(solid * STRIDE * multiplier).order(ByteOrder.nativeOrder());
        var b = ByteBuffer.allocate(fluid * STRIDE * multiplier).order(ByteOrder.nativeOrder());
        for (var face : mesh.faces()) {
            var out = (face.material().flags() & Terrain.FLUID) != 0 ? b : a;
            var uv = catalog.get(face.material().state(), face.direction());
            if (gpu) put(out, mesh.key(), face.x(), face.y(), face.z(), face.width(), face.height(), face.direction(), face.material(), uv);
            else for (int corner : CORNERS) {
                float[] p = TileMesh.corner(face, corner);
                put(out, mesh.key(), p[0], p[1], p[2], (corner == 1 || corner == 2) ? face.width() : 0,
                        corner >= 2 ? face.height() : 0, face.direction(), face.material(), uv);
            }
        }
        return new PackedMesh(mesh.key(), a.array(), b.array(), solid * multiplier, fluid * multiplier,
                gpu, mesh.minY(), mesh.maxY(), stamp);
    }
    private static void put(ByteBuffer out, TilePlan.Key key, float x, float y, float z, float u, float v, int direction,
                             Terrain.Material material, TextureCatalog.Uv uv) {
        out.putInt(key.blockX()).putInt(key.blockZ());
        out.putFloat(x).putFloat(y).putFloat(z).putFloat(u).putFloat(v).putInt(direction);
        out.putInt(material.color()).putFloat(uv.u()).putFloat(uv.v()).putFloat(uv.width()).putFloat(uv.height());
        out.putInt(material.light()).putInt(material.flags()).putInt(material.state());
    }
}
