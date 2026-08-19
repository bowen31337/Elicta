import { lazy, Suspense, type ComponentType } from "react";

import { AppShell } from "./shell/AppShell";
import { buildDestinations } from "./shell/destinations";

type RouteModule = { default: ComponentType };

// File-based routing: any feature directory that exports a `route.tsx` default
// component is mounted automatically. Add a feature by dropping a
// `src/features/<name>/route.tsx` file — this scan picks it up without any
// change here. What the sidebar calls it, and where in the engagement it
// belongs, comes from `shell/destinations.ts`; a feature missing from that
// table still appears, under "More".
const routeModules = import.meta.glob<RouteModule>("./features/*/route.tsx");

const screens = new Map<string, ComponentType>(
  Object.entries(routeModules).map(([path, loader]) => [
    path.split("/")[2],
    lazy(loader as () => Promise<RouteModule>),
  ]),
);

const destinations = buildDestinations([...screens.keys()]);

export function AppRouter() {
  if (destinations.length === 0) {
    return (
      <p className="p-4 text-sm text-neutral-500">No features registered yet.</p>
    );
  }

  return (
    <AppShell
      destinations={destinations}
      renderScreen={(destination) => {
        const Screen = screens.get(destination.feature);
        if (Screen === undefined) return null;
        return (
          <Suspense fallback={null}>
            <Screen />
          </Suspense>
        );
      }}
    />
  );
}
