import { useEffect, useState } from "react";

function detectMobile(): boolean {
  if (typeof window === "undefined") return false;

  const userAgent = window.navigator.userAgent || "";
  const mobileUserAgent = /iPhone|iPad|iPod|Android|Mobile/i.test(userAgent);
  return mobileUserAgent || window.matchMedia("(max-width: 768px)").matches;
}

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(detectMobile);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 768px)");
    const handleChange = () => setIsMobile(detectMobile());

    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    window.addEventListener("resize", handleChange);

    return () => {
      mediaQuery.removeEventListener("change", handleChange);
      window.removeEventListener("resize", handleChange);
    };
  }, []);

  return isMobile;
}
