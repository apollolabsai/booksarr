import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import { useBuildInfo } from "../api/settings";

function isSet(val?: string): val is string {
  return !!val && val !== "unknown" && val !== "";
}

export default function Layout() {
  const { data: buildInfo } = useBuildInfo();

  const branch = isSet(buildInfo?.branch) ? buildInfo.branch : "dev";
  const commitShort = isSet(buildInfo?.commit)
    ? buildInfo.commit.substring(0, 7)
    : "";
  const buildDate = isSet(buildInfo?.date)
    ? new Date(buildInfo.date).toLocaleDateString()
    : "";

  return (
    <div className="flex h-screen bg-slate-900">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
        <footer className="px-6 py-2 text-xs text-slate-600 border-t border-slate-800 flex-shrink-0">
          Booksarr v0.1.0{commitShort ? ` | ${branch} ${commitShort}` : ""}{buildDate ? ` (${buildDate})` : ""}
        </footer>
      </div>
    </div>
  );
}
