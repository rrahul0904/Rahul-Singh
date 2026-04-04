import Link from "next/link";

import styles from "./page.module.css";

const samplePayload = `{
  "name": "Customer 360 Migration",
  "description": "Migration of customer analytics workloads into Snowflake.",
  "source_platform": "Oracle",
  "target_platform": "Snowflake",
  "owner": "Rahul"
}`;

export default function CreateProjectPage() {
  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <section className={styles.hero}>
          <div>
            <h1 className={styles.title}>Create Project</h1>
            <p className={styles.subtitle}>
              This Phase 1 screen defines the project creation flow. The API contract already exists on the branch,
              and this page shows the exact payload shape the backend accepts while the form wiring is being finished.
            </p>
          </div>
          <div className={styles.badge}>Phase 1 · Create Project</div>
        </section>

        <section className={styles.card}>
          <div className={styles.formGrid}>
            <div className={styles.field}>
              <label className={styles.label}>Project name</label>
              <input className={styles.input} value="Customer 360 Migration" readOnly />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Owner</label>
              <input className={styles.input} value="Rahul" readOnly />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Source platform</label>
              <input className={styles.input} value="Oracle" readOnly />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Target platform</label>
              <select className={styles.select} value="Snowflake" readOnly>
                <option>Snowflake</option>
                <option>Databricks</option>
              </select>
            </div>
            <div className={`${styles.field} ${styles.fieldWide}`}>
              <label className={styles.label}>Description</label>
              <textarea
                className={styles.textarea}
                value="Migration of customer analytics workloads into Snowflake."
                readOnly
              />
            </div>
          </div>

          <p className={styles.helper}>
            Next integration step: connect this form to <strong>POST /api/v1/projects</strong> and route back to the
            control plane after creation.
          </p>

          <div className={styles.codeBlock}>{samplePayload}</div>

          <p className={styles.helper}>
            <Link href="/project-control-plane" className={styles.link}>
              Back to Project Control Plane
            </Link>
          </p>
        </section>
      </div>
    </main>
  );
}
