import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { AboutPage } from "./pages/AboutPage";
import { CommandCenter } from "./pages/CommandCenter";
import { ContactPage } from "./pages/ContactPage";
import { DecisionPage } from "./pages/DecisionPage";
import { InvestigatePage } from "./pages/InvestigatePage";
import { NetworkPage } from "./pages/NetworkPage";
import { PayPage } from "./pages/PayPage";

export default function App() {
  return (
    <Routes>
      <Route path="/contact/:token" element={<ContactPage />} />
      <Route path="/*" element={
        <Shell>
          <Routes>
            <Route path="/" element={<CommandCenter />} />
            <Route path="/pay" element={<PayPage />} />
            <Route path="/investigate" element={<InvestigatePage />} />
            <Route path="/investigate/:decisionId" element={<InvestigatePage />} />
            <Route path="/decision/:decisionId" element={<DecisionPage />} />
            <Route path="/network" element={<NetworkPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </Shell>
      } />
    </Routes>
  );
}
