import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  title: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
}

export function DataTable<T>({ columns, rows, getKey, caption }: { columns: Column<T>[]; rows: T[]; getKey: (row: T) => string; caption: string }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map((column) => <th key={column.key} scope="col" data-align={column.align}>{column.title}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={getKey(row)}>{columns.map((column) => <td key={column.key} data-align={column.align}>{column.render(row)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

