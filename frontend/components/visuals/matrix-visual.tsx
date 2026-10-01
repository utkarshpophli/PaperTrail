import type { CellTone, MatrixRow } from "@/lib/story-api";
import { cn } from "@/lib/utils";

const TONE_CLASS: Record<CellTone, string> = {
  low: "bg-not-found-bg text-ink",
  medium: "bg-partial-bg text-ink",
  high: "bg-verified-bg text-ink",
  neutral: "bg-surface-2 text-ink",
};

export function MatrixVisual({ columns, rows }: { columns: string[]; rows: MatrixRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-ui-label">
        <thead>
          <tr>
            <td />
            {columns.map((column, index) => (
              <th key={`${column}-${index}`} scope="col" className="px-2 py-1 text-left font-semibold text-ink">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${row.label}-${rowIndex}`}>
              <th scope="row" className="px-2 py-1 text-left font-semibold text-ink">
                {row.label}
              </th>
              {row.cells.map((cell, cellIndex) => (
                <td key={cellIndex} className={cn("rounded-md px-2 py-1.5", TONE_CLASS[cell.tone])}>
                  {cell.label}
                  {cell.tone !== "neutral" && <span className="sr-only"> ({cell.tone})</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
