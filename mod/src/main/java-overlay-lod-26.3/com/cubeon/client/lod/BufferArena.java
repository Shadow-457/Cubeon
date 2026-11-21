package com.cubeon.client.lod;

import com.mojang.renderpearl.api.buffers.GpuBuffer;
import com.mojang.renderpearl.api.device.GpuDevice;
import java.util.*;

/** Persistent pages, shared across tiles, with coalescing free ranges. Render-thread owned. */
public final class BufferArena implements AutoCloseable {
    public static final class Page {
        public final GpuBuffer buffer;
        final TreeMap<Long, Long> free = new TreeMap<>();
        Page(GpuBuffer buffer, long size) { this.buffer = buffer; free.put(0L, size); }
    }
    public record Slice(Page page, long offset, long length) { }
    private final List<Page> pages = new ArrayList<>();
    private long allocated;
    public long bytes() { return allocated; }
    public Slice allocate(GpuDevice device, int bytes, long limit) {
        if (bytes == 0) return null;
        long length = ((long)bytes + PackedMesh.STRIDE - 1) / PackedMesh.STRIDE * PackedMesh.STRIDE;
        for (Page page : pages) {
            for (var entry : page.free.entrySet()) if (entry.getValue() >= length) {
                long offset = entry.getKey(), remain = entry.getValue() - length;
                page.free.remove(offset); if (remain > 0) page.free.put(offset + length, remain);
                return new Slice(page, offset, length);
            }
        }
        long size = Math.max(4L << 20, length);
        size = (size + PackedMesh.STRIDE - 1) / PackedMesh.STRIDE * PackedMesh.STRIDE;
        if (allocated + size > limit) return null;
        var page = new Page(device.createBuffer(() -> "Cubeon LOD arena", GpuBuffer.USAGE_VERTEX | GpuBuffer.USAGE_COPY_DST, size), size);
        pages.add(page); allocated += size; page.free.clear();
        if (size > length) page.free.put(length, size - length);
        return new Slice(page, 0, length);
    }
    public void release(Slice slice) {
        if (slice == null) return;
        var free = slice.page.free; long offset = slice.offset, length = slice.length;
        var before = free.floorEntry(offset);
        if (before != null && before.getKey() + before.getValue() == offset) {
            offset = before.getKey(); length += before.getValue(); free.remove(before.getKey());
        }
        var after = free.ceilingEntry(offset);
        if (after != null && offset + length == after.getKey()) { length += after.getValue(); free.remove(after.getKey()); }
        free.put(offset, length);
    }
    public void trim() {
        var iterator = pages.iterator();
        while (iterator.hasNext()) {
            Page page = iterator.next();
            if (page.free.size() == 1 && page.free.firstKey() == 0 && page.free.get(0L) == page.buffer.size()) {
                allocated -= page.buffer.size(); page.buffer.close(); iterator.remove();
            }
        }
    }
    public void close() { for (Page page : pages) page.buffer.close(); pages.clear(); allocated = 0; }
}
