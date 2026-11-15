import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MantineProvider } from "@mantine/core"
import { Notifications } from "@mantine/notifications"

import "@mantine/core/styles.css"
import "@mantine/notifications/styles.css"
import "./index.css"
import "@neon/neon.css"

import App from "./App.tsx"
import { neonTheme } from "@neon/mantine"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* The DAQ look (neon_ui): Mantine stays in its dark scheme, NEON's tokens
        draw it bright or dark. */}
    <MantineProvider theme={neonTheme} forceColorScheme="dark">
      <Notifications position="bottom-right" autoClose={4000} />
      <App />
    </MantineProvider>
  </StrictMode>,
)
