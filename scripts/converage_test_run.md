# 1. Run tests and generate the XML report
```bash
poetry run pytest --cov=polyfuseql --cov-report=xml:coverage.xml --cov-report=term
```
# 2. (Optional) Generate HTML report to visually inspect missing coverage locally
```bash
poetry run pytest --cov=polyfuseql --cov-report=html
```
**Result:** You should see a `coverage.xml` file in your project root. You can verify the content looks correct (it should contain `<coverage>` tags). You can also open `htmlcov/index.html` in your browser to see exactly which lines are missing coverage (useful for your 80% goal).

---

### **Phase 2: GitHub Actions Integration**

We need to modify your `ci.yml` to ensure the coverage artifact is available to the SonarQube Action.

#### **4. Update `.github/workflows/ci.yml`**
I have updated your existing workflow. I added the `fetch-depth: 0` (required for Sonar analysis) and the SonarQube scan step *after* the tests run.


http://googleusercontent.com/immersive_entry_chip/2

### **Summary & Next Steps**

1.  **Commit** the changes to `pyproject.toml` and `sonar-project.properties`.
2.  **Add Secrets:** Ensure `SONAR_TOKEN` and `SONAR_HOST_URL` are set in your GitHub Repository Secrets.
3.  **Analyze Coverage:** Once the pipeline runs, look at the SonarQube dashboard.
4.  **Target 80%:** To reach 80%, open the local `htmlcov/index.html`. Look for files with low percentages. Focus on:
    * **Branch Coverage:** Are you testing both the `if` and `else` paths?
    * **Error Handling:** Are you writing tests that specifically trigger your `try/except` blocks?
    * **Edge Cases:** Are you testing `None` inputs or empty lists?