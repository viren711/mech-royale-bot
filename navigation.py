"""Bounded grid routes and reachable cover using only the supplied arena."""
import heapq
import math
import time


class Navigator:
    STEP = 10

    def __init__(self, arena):
        self.arena = arena
        b = arena.bounds
        self.x0, self.y0 = math.ceil(b['minX'] / 10) * 10, math.ceil(b['minY'] / 10) * 10
        self.nx = int((b['maxX'] - self.x0) / 10) + 1
        self.ny = int((b['maxY'] - self.y0) / 10) + 1
        self.points = {}
        self.links = {}
        self.cover_nodes = []
        self.route = []
        self.route_goal = None
        self.route_after = -1
        self.zone_route = []
        self.zone_key = None
        self.zone_after = -1
        self.zone_start = None
        for iy in range(self.ny):
            for ix in range(self.nx):
                x, y = self.x0 + ix * 10, self.y0 + iy * 10
                z = arena.ground(x, y)
                if self.open_point(x, y, z):
                    self.points[(ix, iy)] = (x, y, z)
        for cell, p in self.points.items():
            links = []
            ix, iy = cell
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                neighbor = (ix + dx, iy + dy)
                if neighbor not in self.points:
                    continue
                q = self.points[neighbor]
                if abs(q[2] - p[2]) > math.hypot(dx, dy) * 10:
                    continue
                if dx and dy and ((ix + dx, iy) not in self.points or (ix, iy + dy) not in self.points):
                    continue
                mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                if self.open_point(*mid, arena.ground(*mid)):
                    links.append((neighbor, math.dist(p, q)))
            self.links[cell] = links
            if len(links) < 8:
                self.cover_nodes.append(cell)

    def open_point(self, x, y, z):
        return not any(self.arena.solid(x + dx, y + dy, z + 1.2, z + 9)
                       for dx, dy in ((0, 0), (3, 0), (-3, 0), (0, 3), (0, -3)))

    def nearest(self, pos):
        ix, iy = round((pos[0] - self.x0) / 10), round((pos[1] - self.y0) / 10)
        options = [(x, y) for x in range(ix - 3, ix + 4) for y in range(iy - 3, iy + 4) if (x, y) in self.points]
        return min(options, key=lambda cell: math.dist(pos[:2], self.points[cell][:2]), default=None)

    def path(self, pos, goal, limit=1600):
        deadline = time.perf_counter() + .004
        start, end = self.nearest(pos), self.nearest(goal)
        if start is None or end is None:
            return []
        scores, parents = {start: 0}, {}
        queue = [(math.dist(self.points[start][:2], self.points[end][:2]), 0, start)]
        count = 0
        while queue and count < limit:
            if count % 32 == 0 and time.perf_counter() > deadline:
                break
            _, cost, cell = heapq.heappop(queue)
            if cost != scores.get(cell):
                continue
            count += 1
            if cell == end:
                result = [cell]
                while cell in parents:
                    cell = parents[cell]
                    result.append(cell)
                return [self.points[c] for c in reversed(result)]
            for neighbor, distance in self.links[cell]:
                candidate = cost + distance
                if candidate < scores.get(neighbor, math.inf):
                    scores[neighbor], parents[neighbor] = candidate, cell
                    heapq.heappush(queue, (candidate + math.dist(self.points[neighbor][:2], self.points[end][:2]), candidate, neighbor))
        return []

    def zone_distance(self, pos, zone, now):
        """Estimate travel to safe ground, including a cached obstacle detour."""
        center = zone['next_center']
        radius = max(0, zone['next_radius'] - 12)
        direct = max(0, math.dist(pos[:2], center) - radius)
        if direct == 0:
            return 0
        key = (*center, radius)
        if (key != self.zone_key or now >= self.zone_after or
                self.zone_start is None or math.dist(pos, self.zone_start) > 20):
            self.zone_route = self.path(pos, center)
            self.zone_key, self.zone_after = key, now + 2
            self.zone_start = list(pos)
        if not self.zone_route:
            return direct * 1.25  # Bounded search failure is uncertainty, not zero distance.
        first = min(range(len(self.zone_route)), key=lambda i: math.dist(pos, self.zone_route[i]))
        previous, length = pos, 0
        for point in self.zone_route[first:]:
            length += math.dist(previous, point)
            if math.dist(point[:2], center) <= radius:
                return max(direct, length)
            previous = point
        return max(direct, length + max(0, math.dist(previous[:2], center) - radius))

    def waypoint(self, pos, goal, now):
        # Roofs are handled by local steering; the grid represents ground travel.
        if pos[2] > self.arena.ground(*pos[:2]) + 4:
            return goal
        if self.route_goal is None or math.dist(goal[:2], self.route_goal[:2]) > 15 or now >= self.route_after:
            self.route = self.path(pos, goal)
            self.route_goal = list(goal)
            self.route_after = now + 3
        while self.route and math.dist(pos[:2], self.route[0][:2]) < 3.5:
            self.route.pop(0)
        return self.route[0][:2] if self.route else goal

    def cover(self, pos, enemies, zone):
        deadline = time.perf_counter() + .008
        enemies = sorted(enemies, key=lambda e: math.dist(pos, e['pos']))[:3]
        if not enemies:
            return None
        candidates = sorted((cell for cell in self.cover_nodes
                             if 8 < math.dist(pos, self.points[cell]) < 65
                             and math.dist(self.points[cell][:2], zone['center']) < zone['radius'] - 10),
                            key=lambda cell: math.dist(pos, self.points[cell]))[:36]
        best = None
        for cell in candidates:
            if time.perf_counter() > deadline:
                break
            p = self.points[cell]
            # Hiding just the feet is insufficient: the opponent aims at our body.
            visible = sum(self.arena.clear_shot([*e['pos'][:2], e['pos'][2] + 7], [*p[:2], p[2] + 7]) for e in enemies)
            if visible:
                continue
            route = self.path(pos, p, limit=350)
            if not route:
                continue
            length = math.dist(pos, route[0]) + sum(math.dist(a, b) for a, b in zip(route, route[1:]))
            if length > 85:
                continue
            separation = min(math.dist(p, e['pos']) for e in enemies)
            score = length - min(100, separation) * .2
            if best is None or score < best[0]:
                best = score, p
        return best[1] if best else None
