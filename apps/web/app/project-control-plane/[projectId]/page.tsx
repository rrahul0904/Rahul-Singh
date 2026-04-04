import Link from "next/link";
import { notFound } from "next/navigation";

import styles from "./page.module.css";
import { getProject, getProjectInventory, getProjectSummary } from "../../../lib/projectInventoryClient";

type Props = {
  params: Promise<{ projectId: string }>;
};

function complexityClass(level: "Low" | "Medium" | "High") {
  if (level === "Low") return `${styles.pill} ${styles.low}`;
  if (level === "Medium") return `${styles.pill} ${styles.medium}`;
  return `${styles.pill} ${styles.high}`;
}

export default async function ProjectDetailPage({ params }: Props) {
  const { projectId } = await params;

  const [project, summary, inventory] = await Promise.all([
    getProject(projectId),
    getProjectSummary(projectId),
    getProjectInventory(projectId),
  ]);

  if (!project || !summary) {
    notFound();
  }

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <section className={styles.hero}>
          <div>
            <h1 className={styles.title}>{project.name}</h1>
            <p className={styles.subtitle}>
              {project.description} This Phase 1 screen combines project overview, summary metrics, and an inventory
              drilldown so later discovery, conversion, and validation modules have a clear place to attach.
            </p>
          </div>
          <div className={styles.badge}>{project.target_platform} target</div>
        </section>

        <section className={styles.metrics}>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Owner</div>
            <div className={styles.metricValue}>{project.owner}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Status</div>
            <div className={styles.metricValue}>{project.status}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Progress</div>
            <div className={styles.metricValue}>{project.progress}%</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Inventory Items</div>
            <div className={styles.metricValue}>{summary.total_inventory_items}</div>
          </div>
        </section>

        <section className={styles.grid}>
          <div className={styles.card}>
            <h2>Inventory Drilldown</h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Object</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Complexity</th>
                  </tr>
                </thead>
                <tbody>
                  {inventory.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.object_name}</strong>
                        <div>{item.schema_name}</div>
                      </td>
                      <td>{item.object_type}</td>
                      <td><span className={styles.pill}>{item.status}</span></td>
                      <td><span className={complexityClass(item.complexity)}>{item.complexity}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.card}>
            <h2>Summary</h2>
            <div className={styles.list}>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Tables discovered</div>
                {summary.discovered_tables}
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Views discovered</div>
                {summary.discovered_views}
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Items needing review</div>
                {summary.items_needing_review}
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>What comes next</div>
                Discovery runs, conversion artifacts, and validation results will all attach to this project scope.
              </div>
            </div>
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
