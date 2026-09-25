import { Toaster } from "sonner";
import Home from "./Home";

export default function App() {
  return (
    <>
      <Toaster theme="dark" position="bottom-right" />
      <Home />
    </>
  );
}
