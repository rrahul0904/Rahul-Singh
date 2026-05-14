import React from "react";
import EmptyState from "./EmptyState.jsx";

function normaliseRows(rows) {
  if (!Array.isArray(rows)) return [];
  return rows;
}

function cellValue(row, column, index) {
  if (Array.isArray(row)) return row[index];
  if (row && typeof row === "object") return row[column];
  return row;
}

function displayCell(value) {
  if (value === null) return <span style={{ color: "var(--text3)" }}>NULL</span>;
  if (value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ResultGrid({ columns = [], rows = [], emptyTitle = "No rows", emptyMessage = "", maxRows = 500 }) {
  const safeRows = normaliseRows(rows).slice(0, maxRows);
  const safeColumns = Array.isArray(columns) && columns.length
    ? columns.map((c) => (typeof c === "string" ? c : c?.name || c?.key || String(c)))
    : [];

  if (!safeColumns.length || !safeRows.length) {
    return <EmptyState compact title={emptyTitle} message={emptyMessage} />;
  }

  return (
    <div className="result-table pq-result-grid">
      <table>
        <thead>
          <tr>{safeColumns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {safeColumns.map((column, columnIndex) => (
                <td key={`${rowIndex}-${column}`} className="td-mono">{displayCell(cellValue(row, column, columnIndex))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
