import Link from "next/link";

import styles from "./page.module.css";
import { getDiscoveryResults, getDiscoveryRuns, getDiscoverySummary } from "../../lib/discoveryClient";

function complexityClass(level: "Low" | "Medium" | "High", stylesObj: typeof styles) {
  if (level === "Low") return `${stylesObj.pill} ${stylesObj.low}`;
  if (level === "Medium") return `${stylesObj.pill} ${stylesObj.medium}`;
  return `${stylesObj.pill} ${stylesObj.high}`;
}

export default async function DiscoveryDashboardPage() {
  const runs = await getDiscoveryRuns();
  const activeRun = runs[0] ?? null;
  const summary = activeRun ? await getDiscoverySummary(activeRun.id) : null;
  const results = activeRun ? await getDiscoveryResults(activeRun.id) : [];

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <section className={styles.hero}>
          <div>
            <h1 className={styles.title}>Discovery and Assessment</h1>
            <p className={styles.subtitle}>
              Phase 2 turns source-system scanning into migration-ready scope. This dashboard shows discovery runs,
              complexity distribution, and the first object-level assessment outputs.
            </p>
          </div>
          <div className={styles.badge}>Phase 2 · Discovery</div>
        </section>

        <section className={styles.metrics}>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Discovery Runs</div>
            <div className={styles.metricValue}>{runs.length}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Objects Found</div>
            <div className={styles.metricValue}>{summary?.object_count ?? 0}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>High Complexity</div>
            <div className={styles.metricValue}>{summary?.high_complexity_count ?? 0}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Dependency Edges</div>
            <div className={styles.metricValue}>{summary?.dependency_edges ?? 0}</div>
          </div>
        </section>

        <section className={styles.grid}>
          <div className={styles.card}>
            <h2>Discovery Results</h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Object</th>
                    <th>Type</th>
                    <th>Complexity</th>
                    <th>Dependencies</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result) => (
                    <tr key={result.id}>
                      <td>
                        <strong>{result.object_name}</strong>
                        <div>{result.schema_name}</div>
                      </td>
                      <td>{result.object_type}</td>
                      <td>
                        <span className={complexityClass(result.complexity, styles)}>{result.complexity}</span>
                      </td>
                      <td>{result.dependency_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.card}>
            <h2>Run Overview</h2>
            {activeRun ? (
              <div className={styles.list}>
                <div className={styles.listItem}>
                  <div className={styles.listTitle}>Project</div>
                  {activeRun.project_id}
                </div>
                <div className={styles.listItem}>
                  <div className={styles.listTitle}>Source platform</div>
                  {activeRun.source_platform}
                </div>
                <div className={styles.listItem}>
                  <div className={styles.listTitle}>Connector type</div>
                  {activeRun.connector_type}
                </div>
                <div className={styles.listItem}>
                  <div className={styles.listTitle}>Status</div>
                  {activeRun.status}
                </div>
              </div>
            ) : (
              <p>No discovery runs yet.</p>
            )}

            <div style={{ marginTop: 18 }}>
              <Link href="/project-control-plane" className={styles.link}>
                Back to Project Control Plane
              </Link>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
