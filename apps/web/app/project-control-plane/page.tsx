import Link from "next/link";

import styles from "./page.module.css";
import { getProjects } from "../../lib/projectInventoryClient";

export default async function ProjectControlPlanePage() {
  const projects = await getProjects();

  const totalProjects = projects.length;
  const snowflakeProjects = projects.filter((project) => project.target_platform === "Snowflake").length;
  const databricksProjects = projects.filter((project) => project.target_platform === "Databricks").length;
  const avgProgress = totalProjects
    ? Math.round(projects.reduce((sum, project) => sum + project.progress, 0) / totalProjects)
    : 0;

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <section className={styles.hero}>
          <div>
            <h1 className={styles.title}>Project Control Plane</h1>
            <p className={styles.subtitle}>
              This is the Phase 1 frontend screen for project list and migration ownership. It reads from the
              new Project and Inventory API when available and falls back to seeded data during early wiring.
            </p>
          </div>
          <div className={styles.badge}>Phase 1 · Project and Inventory</div>
        </section>

        <section className={styles.metrics}>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Projects</div>
            <div className={styles.metricValue}>{totalProjects}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Snowflake Targets</div>
            <div className={styles.metricValue}>{snowflakeProjects}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Databricks Targets</div>
            <div className={styles.metricValue}>{databricksProjects}</div>
          </div>
          <div className={styles.card}>
            <div className={styles.metricLabel}>Average Progress</div>
            <div className={styles.metricValue}>{avgProgress}%</div>
          </div>
        </section>

        <section className={styles.grid}>
          <div className={styles.card}>
            <h2>Projects</h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Source</th>
                    <th>Target</th>
                    <th>Status</th>
                    <th>Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((project) => (
                    <tr key={project.id}>
                      <td>
                        <span className={styles.projectName}>{project.name}</span>
                        <span className={styles.muted}>{project.description}</span>
                        <span className={styles.muted}>Owner: {project.owner}</span>
                      </td>
                      <td>{project.source_platform}</td>
                      <td>{project.target_platform}</td>
                      <td>
                        <span className={styles.statusPill}>{project.status}</span>
                      </td>
                      <td>
                        {project.progress}%
                        <div className={styles.progressBar}>
                          <span style={{ width: `${project.progress}%` }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.card}>
            <h2>Phase 1 Notes</h2>
            <div className={styles.list}>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Project context first</div>
                Discovery, conversion, validation, and query history all attach to project scope.
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>API already defined</div>
                The Phase 1 branch includes project list, create, detail, summary, and inventory endpoints.
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Next UI step</div>
                Add a dedicated project detail and inventory drilldown screen backed by the same API client.
              </div>
              <div className={styles.listItem}>
                <div className={styles.listTitle}>Current route</div>
                Open this screen at <strong>/project-control-plane</strong> once the branch is merged.
              </div>
            </div>
            <div style={{ marginTop: 18 }}>
              <Link href="/" className={styles.projectName}>
                Back to main app
              </Link>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
