import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import MobileNav from "./MobileNav";
import { useBuildInfo } from "../api/settings";
import { useIsMobile } from "../hooks/useIsMobile";

function isSet(val?: string): val is string {
  return !!val && val !== "unknown" && val !== "";
}

export default function Layout() {
  const { data: buildInfo } = useBuildInfo();
  const isMobile = useIsMobile();

  const branch = isSet(buildInfo?.branch) ? buildInfo.branch : "dev";
  const commitShort = isSet(buildInfo?.commit)
    ? buildInfo.commit.substring(0, 7)
    : "";
  const buildDate = isSet(buildInfo?.date)
    ? new Date(buildInfo.date).toLocaleDateString()
    : "";

  return (
    <div className="flex h-screen bg-slate-900">
      {!isMobile && <Sidebar />}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {isMobile && (
          <div className="border-b border-slate-800 px-4 py-3">
            <h1 className="text-lg font-bold text-emerald-400">Booksarr</h1>
          </div>
        )}
        <main className={`flex-1 overflow-y-auto ${isMobile ? "px-3 py-4" : "p-6"}`}>
          <Outlet />
        </main>
        <footer className={`flex-shrink-0 border-t border-slate-800 text-xs text-slate-600 ${isMobile ? "px-4 py-2" : "px-6 py-2"}`}>
          Booksarr v0.1.0{commitShort ? ` | ${branch} ${commitShort}` : ""}{buildDate ? ` (${buildDate})` : ""}
        </footer>
        {isMobile && <MobileNav />}
      </div>
    </div>
  );
}
