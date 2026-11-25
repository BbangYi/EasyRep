"use client";

import { Component, lazy, Suspense, type ComponentProps, type ReactNode } from "react";

type ChartProps = ComponentProps<typeof import("./environment-chart").EnvironmentChart>;
// The home list does not need the plotting library. Load it on the first detail visit.
const Chart = lazy(() => import("./environment-chart").then((module) => ({ default: module.EnvironmentChart })));

class ChartBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) {
      return (
        <section className="panel chart-loading">
          <p role="alert">환경 이력을 불러오지 못했습니다.</p>
          <button className="button" onClick={() => window.location.reload()}>새로고침</button>
        </section>
      );
    }
    return this.props.children;
  }
}

export function EnvironmentChartLoader(props: ChartProps) {
  return (
    <ChartBoundary>
      <Suspense fallback={<section className="panel chart-loading" role="status" aria-label="환경 이력 불러오는 중">환경 이력을 불러오는 중입니다.</section>}>
        <Chart {...props} />
      </Suspense>
    </ChartBoundary>
  );
}
