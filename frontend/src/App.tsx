import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Loading } from "./components/ui";
import { AboutPage } from "./pages/AboutPage";
import { AccountPage } from "./pages/AccountPage";
import { CasePage } from "./pages/CasePage";
import { CommandCenter } from "./pages/CommandCenter";
import { ContactPage } from "./pages/ContactPage";
import { DecisionPage } from "./pages/DecisionPage";
import { GuardPage } from "./pages/GuardPage";
import { InvestigationsPage } from "./pages/InvestigationsPage";
import { PayPage } from "./pages/PayPage";

// Network Intelligence carries three.js + Cytoscape: code-split so every other page stays light.
const NetworkPage = lazy(() => import("./pages/NetworkPage").then((m) => ({ default: m.NetworkPage })));

function Pending({ title }: { title: string }) {
  return <div className="notice info">{title} is being rebuilt in this branch.</div>;
}

/** Old v1 routes → their v2 homes (FINAL_PARALLEL_PLAN §1). */
function Redirect({ to }: { to: (p: Record<string, string | undefined>) => string }) {
  const params = useParams();
  const loc = useLocation();
  return <Navigate to={to(params) + (loc.search || "")} replace />;
}

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Loading text="Loading module" />}>{children}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/contact/:token" element={<ContactPage />} />
      <Route path="/pay" element={<PayPage />} />
      <Route path="/*" element={
        <Shell>
          <Routes>
            <Route path="/" element={<CommandCenter />} />
            <Route path="/guard" element={<GuardPage />} />
            <Route path="/network" element={<Lazy><NetworkPage /></Lazy>} />
            <Route path="/detection" element={<Pending title="Detection & Models" />} />
            <Route path="/investigations" element={<InvestigationsPage />} />
            <Route path="/investigations/decision/:decisionId" element={<CasePage />} />
            <Route path="/investigations/account/:accountId" element={<AccountPage />} />
            <Route path="/interventions" element={<Pending title="Interventions" />} />
            <Route path="/governance" element={<AboutPage />} />
            <Route path="/governance/decision/:decisionId" element={<DecisionPage />} />
            <Route path="/lab" element={<Pending title="Scenario Lab" />} />
            <Route path="/health" element={<Pending title="System Health" />} />
            {/* v1 → v2 redirects */}
            <Route path="/investigate" element={<Navigate to="/investigations" replace />} />
            <Route path="/investigate/:id" element={<Redirect to={(p) => `/investigations/decision/${p.id}`} />} />
            <Route path="/decision/:id" element={<Redirect to={(p) => `/governance/decision/${p.id}`} />} />
            <Route path="/about" element={<Navigate to="/governance?tab=positioning" replace />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </Shell>
      } />
    </Routes>
  );
}
