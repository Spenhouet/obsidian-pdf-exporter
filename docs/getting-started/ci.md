# CI integration

ope runs without Obsidian, a browser or Node.js, so an export or a redline is one command in any CI system. Two ways to get ope and its native libraries into a pipeline:

| Way | Fits |
| --- | ---- |
| [Container image](#container-image) | Pipelines where each step runs in a container: GitLab CI, Kubernetes, Argo Workflows, Tekton, Jenkins agents, GitHub Actions container jobs |
| [Install in the job](#github-actions-with-uv) | GitHub Actions runners and other virtual machines |

Redlines need the git history of both commits. Clone with full history (`fetch-depth: 0` in `actions/checkout`, `GIT_DEPTH: 0` in GitLab CI). Images stored with Git LFS need `git lfs pull` before the export, otherwise the PDF shows the LFS pointer files.

## Container image

Each release is published to the GitHub Container Registry for `linux/amd64` and `linux/arm64`:

```text
ghcr.io/spenhouet/obsidian-pdf-exporter:<version>
ghcr.io/spenhouet/obsidian-pdf-exporter:latest
```

The image holds the released package from PyPI, the native libraries WeasyPrint needs, pandoc, fonts with emoji, and git with git-lfs. The entry point is `ope` and the working directory is `/vault`. Mounted repositories count as safe for git, so redlines work on a checkout that belongs to another user. Pin a version in pipelines, so a new release does not change the PDFs unnoticed.

```bash
docker run --rm -v "$PWD:/vault" ghcr.io/spenhouet/obsidian-pdf-exporter:0.16.3 \
  export Handbook --title "Team handbook" --output handbook.pdf
```

Custom templates and fonts are read from the mounted folder like on a local install: `--template ./templates/my-template`.

### GitHub Actions container job

```yaml
jobs:
  pdf:
    runs-on: ubuntu-latest
    container: ghcr.io/spenhouet/obsidian-pdf-exporter:0.16.3
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history for redline and the version label
      - run: ope export ./Handbook --title "Team handbook" --version "${{ github.ref_name }}" -o handbook.pdf
      - uses: actions/upload-artifact@v4
        with:
          name: handbook
          path: handbook.pdf
```

### GitLab CI

The entry point is cleared, so GitLab runs the job script in a shell.

```yaml
handbook:
  image:
    name: ghcr.io/spenhouet/obsidian-pdf-exporter:0.16.3
    entrypoint: [""]
  variables:
    GIT_DEPTH: 0   # full history for redline and the version label
  script:
    - ope export ./Handbook --title "Team handbook" --version "$CI_COMMIT_REF_NAME" -o handbook.pdf
  artifacts:
    paths:
      - handbook.pdf
```

### Kubernetes and Argo Workflows

A step of an Argo workflow that exports a folder of a repository cloned to a shared volume by an earlier step:

```yaml
- name: export
  container:
    image: ghcr.io/spenhouet/obsidian-pdf-exporter:0.16.3
    workingDir: /work/repo
    args: [export, Handbook, --title, Team handbook, --output, /work/out/handbook.pdf]
    resources:
      requests:
        memory: 1Gi
    volumeMounts:
      - name: work
        mountPath: /work
```

Memory grows with the size of the export. A folder of a few hundred notes with images needs about 3 GB. Several exports of the same checkout can run at the same time.

## GitHub Actions with uv

On a GitHub Actions runner, install ope with uv and let `ope setup` install the native libraries:

```yaml
jobs:
  pdf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history for redline and the version label
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install obsidian-pdf-exporter
      - run: ope setup --yes
      - run: ope export ./Handbook --title "Team handbook" --version "${{ github.ref_name }}" -o handbook.pdf
      - uses: actions/upload-artifact@v4
        with:
          name: handbook
          path: handbook.pdf
```

[Mermaid](../obsidian/mermaid.md) diagrams are drawn inside ope, so the runner needs no Node.js or browser.

The [Redline usage](../redline/usage.md#in-ci) page has workflows that attach a redline to a pull request and to a release.
