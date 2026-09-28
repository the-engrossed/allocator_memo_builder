import { AppShell } from "./components/AppShell";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <AppShell activeStep={0}>
      <UploadPage />
    </AppShell>
  );
}
