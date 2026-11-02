package com.cubeon.client.cosmetics;

/** Tick-only movement gate. No timers, world edits, network or render-frame emission. */
public final class TrailEmission {
    private Object world;
    private String selection;
    private double x, y, z;
    private boolean ready;
    private int lastAge;

    public void reset() { world = null; selection = null; ready = false; }

    public boolean step(Object context, String id, int age, double px, double py, double pz,
                        boolean grounded) {
        if (context != world || !java.util.Objects.equals(id, selection) || age < lastAge) {
            world = context; selection = id; ready = false;
        }
        double dx = px-x, dz = pz-z;
        boolean emit = ready && id != null && grounded && age-lastAge >= 4
                && dx*dx+dz*dz >= .025 && dx*dx+dz*dz < 4 && Math.abs(py-y) < 1;
        if (!ready || age-lastAge >= 4 || !grounded) {
            x = px; y = py; z = pz; lastAge = age; ready = true;
        }
        return emit;
    }
}
