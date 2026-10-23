"""Depth ordering for disjoint textured cuboids painted by the native client."""


def _area(polygon):
    return sum(first[0] * second[1] - second[0] * first[1]
               for first, second in zip(polygon, polygon[1:] + polygon[:1])) / 2


def _intersection(subject, clip):
    orientation = 1 if _area(clip) > 0 else -1
    for start, end in zip(clip, clip[1:] + clip[:1]):
        if not subject:
            break
        edge_x, edge_y = end[0] - start[0], end[1] - start[1]

        def distance(point):
            return orientation * (edge_x * (point[1] - start[1]) - edge_y * (point[0] - start[0]))

        clipped = []
        previous = subject[-1]
        previous_distance = distance(previous)
        for current in subject:
            current_distance = distance(current)
            previous_inside, current_inside = previous_distance >= -1e-6, current_distance >= -1e-6
            if previous_inside != current_inside:
                fraction = previous_distance / (previous_distance - current_distance)
                clipped.append((previous[0] + fraction * (current[0] - previous[0]),
                                previous[1] + fraction * (current[1] - previous[1])))
            if current_inside:
                clipped.append(current)
            previous, previous_distance = current, current_distance
        subject = clipped
    return subject


def order_faces(faces, previous=None):
    priority = {index: position for position, index in enumerate(previous or [])}
    polygons = [face.polygon for face in faces]
    bounds = [(min(point[0] for point in polygon), min(point[1] for point in polygon),
               max(point[0] for point in polygon), max(point[1] for point in polygon)) for polygon in polygons]
    successors = [set() for face in faces]
    incoming = [0 for face in faces]
    for first_index, first in enumerate(faces):
        for second_index in range(first_index + 1, len(faces)):
            first_bounds, second_bounds = bounds[first_index], bounds[second_index]
            if (first_bounds[2] <= second_bounds[0] or second_bounds[2] <= first_bounds[0]
                    or first_bounds[3] <= second_bounds[1] or second_bounds[3] <= first_bounds[1]):
                continue
            overlap = _intersection(polygons[first_index], polygons[second_index])
            if len(overlap) < 3 or abs(_area(overlap)) < 0.01:
                continue
            differences = [first.depth_at(point) - faces[second_index].depth_at(point) for point in overlap]
            if min(differences) >= -1e-5 and max(differences) > 1e-5:
                behind, ahead = second_index, first_index
            elif max(differences) <= 1e-5 and min(differences) < -1e-5:
                behind, ahead = first_index, second_index
            else:
                continue
            successors[behind].add(ahead)
            incoming[ahead] += 1
    remaining = set(range(len(faces)))
    ordered = []
    while remaining:
        ready = [index for index in remaining if incoming[index] == 0]
        chosen = min(ready or remaining,
                     key=lambda index: (priority.get(faces[index].index, len(priority)), faces[index].depth))
        remaining.remove(chosen)
        ordered.append(faces[chosen])
        for successor in successors[chosen]:
            incoming[successor] -= 1
    return ordered
