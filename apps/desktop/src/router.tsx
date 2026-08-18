import { lazy, Suspense, type ComponentType } from "react";

type RouteModule = { default: ComponentType };

// File-based routing: any feature directory that exports a `route.tsx`
// default component is mounted automatically. Add a feature by dropping a
// `src/features/<name>/route.tsx` file — this scan picks it up without any
// change here.
const routeModules = import.meta.glob<RouteModule>("./features/*/route.tsx");

const routes = Object.entries(routeModules).map(([path, loader]) => ({
  feature: path.split("/")[2],
  Component: lazy(loader as () => Promise<RouteModule>),
}));

export function AppRouter() {
  if (routes.length === 0) {
    return (
      <p className="p-4 text-sm text-neutral-500">No features registered yet.</p>
    );
  }

  return (
    <Suspense fallback={null}>
      {routes.map(({ feature, Component }) => (
        <Component key={feature} />
      ))}
    </Suspense>
  );
}
