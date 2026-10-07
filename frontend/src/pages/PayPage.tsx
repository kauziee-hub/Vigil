// /pay?as=<customer> — the customer-only kiosk. No bank console, no assessment: just the phone.
import { useSearchParams } from "react-router-dom";
import { CustomerDevice } from "../components/CustomerDevice";

export function PayPage() {
  const [params] = useSearchParams();
  const payer = params.get("as") || "ramesh@vigil";
  return (
    <div className="kiosk">
      <CustomerDevice payer={payer} kiosk />
      <div className="kiosk-foot">Vigil demo · customer view · synthetic accounts · payments are DEMO or Razorpay TEST — no real money moves.</div>
    </div>
  );
}
