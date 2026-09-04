import { ActionIcon, Button, createTheme, Popover, rem, Select, TextInput } from "@mantine/core"

/**
 * Theme for a dense readout.
 *
 * This is deliberately the opposite of the actuator panel next door. That page
 * is a control surface: a handful of buttons that move hardware, sized to be
 * hit from a metre away, with colour spent on making the live axis obvious.
 * This page is a table of fifty-odd channels and up to eighteen parameters
 * each, and the only thing that helps is fitting more of it on screen at once.
 *
 * So: 12 px base instead of 15, four-pixel spacing steps instead of ten,
 * square corners, and no elevation anywhere. Mantine is here for the controls
 * in the toolbar -- the table itself is a plain `<table>` styled in index.css,
 * because no component library's table is as tight as one written by hand.
 *
 * Colour carries one meaning each and nothing else is tinted: green is
 * powered, red is a fault bit, amber is a value that moved since the snapshot
 * you are comparing against.
 */
export const theme = createTheme({
  primaryColor: "blue",
  primaryShade: 7,
  defaultRadius: "sm",

  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: '"Geist Mono Variable", ui-monospace, SFMono-Regular, monospace',
  headings: { fontWeight: "600" },

  fontSizes: {
    xs: rem(11),
    sm: rem(12),
    md: rem(12),
    lg: rem(13),
    xl: rem(15),
  },
  lineHeights: { xs: "1.3", sm: "1.35", md: "1.4" },
  spacing: { xs: rem(4), sm: rem(6), md: rem(10), lg: rem(16), xl: rem(24) },

  components: {
    // Every control in the toolbar is one row tall, so the two header rows
    // stay under 60 px between them.
    Button: Button.extend({ defaultProps: { size: "compact-xs", radius: "sm" } }),
    ActionIcon: ActionIcon.extend({ defaultProps: { size: "sm", variant: "subtle" } }),
    TextInput: TextInput.extend({ defaultProps: { size: "xs" } }),
    Select: Select.extend({ defaultProps: { size: "xs" } }),
    Popover: Popover.extend({ defaultProps: { shadow: "sm", radius: "sm" } }),
  },
})
