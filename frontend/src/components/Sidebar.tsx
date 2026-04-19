import { NavLink, useLocation } from "react-router-dom";
import { useScanStatus } from "../api/settings";

const links = [
  { to: "/", label: "Authors", icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" },
  { to: "/books", label: "Books", icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" },
  { to: "/irc-downloads", label: "IRC Downloads", icon: "M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-4l-3 3-3-3z" },
];

const settingsLinks: { to: string; label: string; children?: { to: string; label: string }[] }[] = [
  { to: "/settings/api-keys", label: "API Keys" },
  {
    to: "/settings/profiles",
    label: "Profiles",
    children: [{ to: "/books/hidden", label: "Hidden Books" }],
  },
  { to: "/settings/metadata-refreshes", label: "Metadata Refreshes" },
  { to: "/settings/irc", label: "IRC" },
  { to: "/settings/logs", label: "Logs" },
];

export default function Sidebar() {
  const location = useLocation();
  const { data: scanStatus } = useScanStatus(true);
  const isScanning = scanStatus?.status === "scanning";
  const settingsActive = location.pathname.startsWith("/settings");

  return (
    <aside className="w-56 bg-slate-800 border-r border-slate-700 flex flex-col">
      <div className="p-4 border-b border-slate-700">
        <h1 className="text-xl font-bold text-emerald-400">Booksarr</h1>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "bg-slate-700 text-emerald-400"
                  : "text-slate-300 hover:bg-slate-700/50 hover:text-slate-100"
              }`
            }
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={link.icon} />
            </svg>
            {link.label}
          </NavLink>
        ))}

        <div className="pt-2">
          <NavLink
            to="/settings/api-keys"
            className={() =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                settingsActive
                  ? "bg-slate-700 text-emerald-400"
                  : "text-slate-300 hover:bg-slate-700/50 hover:text-slate-100"
              }`
            }
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Settings
          </NavLink>
          <div className="mt-1 ml-5 space-y-0.5 border-l border-slate-700 pl-3">
            {settingsLinks.map((link) => {
              const active = location.pathname === link.to;
              return (
                <div key={link.to}>
                  <NavLink
                    to={link.to}
                    className={() =>
                      `block rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                        active
                          ? "bg-slate-700/70 text-emerald-400"
                          : "text-slate-400 hover:bg-slate-700/40 hover:text-slate-200"
                      }`
                    }
                  >
                    {link.label}
                  </NavLink>
                  {link.children?.map((child) => {
                    const childActive = location.pathname === child.to;
                    return (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        className={() =>
                          `block rounded-md py-1 pl-5 pr-3 text-xs font-medium transition-colors ${
                            childActive
                              ? "text-emerald-400"
                              : "text-slate-500 hover:text-slate-300"
                          }`
                        }
                      >
                        {child.label}
                      </NavLink>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </nav>

      {/* Scan Status Footer */}
      {isScanning && scanStatus && (
        <div className="p-3 border-t border-slate-700">
          <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
            Scanning...
          </div>
          <div className="w-full bg-slate-700 rounded-full h-1.5">
            <div
              className="bg-emerald-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${scanStatus.progress}%` }}
            />
          </div>
          <p className="text-xs text-slate-500 mt-1 truncate">{scanStatus.message}</p>
        </div>
      )}
    </aside>
  );
}
