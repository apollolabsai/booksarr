import { type RefObject, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

type VirtualRange = {
  endIndex: number;
  offsetTop: number;
  scrollToIndex: (index: number) => void;
  startIndex: number;
  totalSize: number;
  virtualIndexes: number[];
};

type ScrollParent = HTMLElement | Window;

export function useWindowVirtualRange<T extends HTMLElement>(
  containerRef: RefObject<T>,
  count: number,
  estimateSize: number,
  overscan: number = 6,
): VirtualRange {
  const frameRef = useRef<number | null>(null);
  const [viewport, setViewport] = useState({
    height: typeof window === "undefined" ? 0 : window.innerHeight,
    scrollY: typeof window === "undefined" ? 0 : window.scrollY,
    top: 0,
  });

  const measure = useCallback(() => {
    const element = containerRef.current;
    const scrollParent = element ? getScrollParent(element) : window;
    const { height, scrollTop, top } = getScrollMetrics(element, scrollParent);
    setViewport({
      height,
      scrollY: scrollTop,
      top,
    });
  }, [containerRef]);

  const scheduleMeasure = useCallback(() => {
    if (frameRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = null;
      measure();
    });
  }, [measure]);

  useLayoutEffect(() => {
    measure();
  }, [count, estimateSize, measure]);

  useEffect(() => {
    const element = containerRef.current;
    const scrollParent = element ? getScrollParent(element) : window;
    scheduleMeasure();
    scrollParent.addEventListener("scroll", scheduleMeasure, { passive: true });
    window.addEventListener("resize", scheduleMeasure);
    return () => {
      scrollParent.removeEventListener("scroll", scheduleMeasure);
      window.removeEventListener("resize", scheduleMeasure);
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, [scheduleMeasure]);

  const safeEstimate = Math.max(1, estimateSize);
  const visibleStart = Math.floor(Math.max(0, viewport.scrollY - viewport.top) / safeEstimate);
  const visibleEnd = Math.ceil(Math.max(0, viewport.scrollY + viewport.height - viewport.top) / safeEstimate);
  const startIndex = Math.max(0, visibleStart - overscan);
  const endIndex = Math.min(count, visibleEnd + overscan);
  const offsetTop = startIndex * safeEstimate;
  const totalSize = count * safeEstimate;

  const virtualIndexes = useMemo(() => {
    return Array.from({ length: Math.max(0, endIndex - startIndex) }, (_, index) => startIndex + index);
  }, [endIndex, startIndex]);

  const scrollToIndex = useCallback((index: number) => {
    const clamped = Math.min(Math.max(0, index), Math.max(0, count - 1));
    const element = containerRef.current;
    const scrollParent = element ? getScrollParent(element) : window;
    const { top } = getScrollMetrics(element, scrollParent);
    const scrollTop = Math.max(0, top + clamped * safeEstimate - 24);
    scrollParent.scrollTo({
      top: scrollTop,
      behavior: "smooth",
    });
  }, [containerRef, count, safeEstimate]);

  return {
    endIndex,
    offsetTop,
    scrollToIndex,
    startIndex,
    totalSize,
    virtualIndexes,
  };
}

function getScrollParent(element: HTMLElement): ScrollParent {
  let parent = element.parentElement;
  while (parent) {
    const overflowY = window.getComputedStyle(parent).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") {
      return parent;
    }
    parent = parent.parentElement;
  }
  return window;
}

function getScrollMetrics(element: HTMLElement | null, scrollParent: ScrollParent) {
  if (scrollParent === window) {
    return {
      height: window.innerHeight,
      scrollTop: window.scrollY,
      top: element ? element.getBoundingClientRect().top + window.scrollY : 0,
    };
  }

  const parent = scrollParent as HTMLElement;
  const parentRect = parent.getBoundingClientRect();
  return {
    height: parent.clientHeight,
    scrollTop: parent.scrollTop,
    top: element ? element.getBoundingClientRect().top - parentRect.top + parent.scrollTop : 0,
  };
}
