import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/trackb", label: "Harness 1: Retrieval + Guardrails" },
  { to: "/trackb/harness2", label: "Harness 2: Build + Trend Analysis" },
  { to: "/trackb/harness2/history", label: "Harness 2: History Search" },
  { to: "/trackb/history", label: "Track B History" },
];

function linkClass(active: boolean): string {
  if (active) {
    return "aw-side-link aw-side-link-active";
  }
  return "aw-side-link";
}

interface AppSidebarProps {
  onCollapse: () => void;
}

export function AppSidebar({ onCollapse }: AppSidebarProps) {
  return (
    <aside className="aw-card aw-sidebar backdrop-blur">
      <div className="flex items-start justify-between gap-2 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-[#1E293B]">
            Deep Report
          </h1>
          <p className="aw-subtle mt-1 text-xs">Track B Harness Console</p>
        </div>
        <button
          type="button"
          className="rounded-md border border-slate-300 px-2 py-1 text-sm text-[#1E293B] transition hover:bg-slate-50"
          onClick={onCollapse}
          title="Hide menu"
          aria-label="Hide menu"
        >
          ☰
        </button>
      </div>

      <nav className="mt-4 flex flex-col gap-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end
            className={({ isActive }) => linkClass(isActive)}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
