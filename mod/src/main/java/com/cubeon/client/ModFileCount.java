package com.cubeon.client;

import java.nio.file.Path;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.TreeSet;

/** Count loaded top-level mod sources, rather than the modules bundled inside them. */
public final class ModFileCount {
    public record Source(String type, String kind, List<Path> paths) { }
    private ModFileCount() { }
    public static int count(Collection<Source> sources) {
        var unique = new HashSet<List<String>>();
        for (Source source : sources) {
            if ("builtin".equals(source.type()) || !"PATH".equals(source.kind()) || source.paths().isEmpty()) continue;
            var paths = new TreeSet<String>();
            for (Path path : source.paths()) paths.add(path.toAbsolutePath().normalize().toString());
            unique.add(List.copyOf(paths));
        }
        return unique.size();
    }
}
