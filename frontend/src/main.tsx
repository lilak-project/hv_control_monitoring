import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MantineProvider } from "@mantine/core"
import { Notifications } from "@mantine/notifications"

import "@mantine/core/styles.css"
import "@mantine/notifications/styles.css"
import "./index.css"

import App from "./App.tsx"
import { theme } from "./theme.ts"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Light only: this runs on a lit bench, and a dark panel washes out. */}
    <MantineProvider theme={theme} forceColorScheme="light">
      <Notifications position="bottom-right" autoClose={4000} />
      <App />
    </MantineProvider>
  </StrictMode>,
)
