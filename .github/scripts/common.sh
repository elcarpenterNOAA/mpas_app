# Shared resources for workflow scripts.

CI_CONDA_SH="$CI_CONDA_DIR/etc/profile.d/conda.sh"

ci_conda_activate() {
  . "$CI_CONDA_SH"
  if [[ -z "$1" ]]; then
    conda activate
  else
    conda activate "$1"
  fi
}
