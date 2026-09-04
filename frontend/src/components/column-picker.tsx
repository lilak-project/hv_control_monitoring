import { Button, Checkbox, Group, Popover, Stack } from "@mantine/core"
import { Columns3 } from "lucide-react"

import { CORE_PARAMS } from "@/lib/columns"
import { columnLabel } from "@/lib/format"
import type { ParamSpec } from "@/lib/types"

/**
 * Which of the boards' parameters are on screen.
 *
 * An A1542HSN reports seventeen and the low-voltage card eighteen; all of them
 * at once is a table nobody can read across. The default is the six you check
 * on a walk past the rack, and the rest are one click away.
 */
export function ColumnPicker({
  params,
  chosen,
  onChange,
}: {
  params: ParamSpec[]
  chosen: Set<string>
  onChange: (chosen: Set<string>) => void
}) {
  const toggle = (name: string) => {
    const next = new Set(chosen)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    onChange(next)
  }

  const core = new Set(params.filter((spec) => CORE_PARAMS.includes(spec.name)).map((s) => s.name))

  return (
    <Popover position="bottom-start" withArrow>
      <Popover.Target>
        <Button variant="default" leftSection={<Columns3 size={13} />}>
          Columns {chosen.size}/{params.length}
        </Button>
      </Popover.Target>
      <Popover.Dropdown p="xs">
        <Stack gap="xs">
          <Group gap="xs">
            <Button variant="default" onClick={() => onChange(core)}>
              Core
            </Button>
            <Button variant="default" onClick={() => onChange(new Set(params.map((s) => s.name)))}>
              All
            </Button>
          </Group>
          <div className="columns">
            {params.map((spec) => (
              <Checkbox
                key={spec.name}
                size="xs"
                label={columnLabel(spec)}
                checked={chosen.has(spec.name)}
                onChange={() => toggle(spec.name)}
              />
            ))}
          </div>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  )
}
