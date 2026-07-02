"""
Kubeflow-pipeline for LayoutLMv3-finjustering.

    eksporter (Label Studio) → konverter (LayoutLMv3-format) → finjuster

Kjøres manuelt fra KFP-UI-et eller på tidsplan (recurring run) —
typisk etter en bunke korreksjoner i Label Studio.

Alle steg bruker trenings-imaget (nav/trening:lokal) og deler
PVC-ene nav-data (/data) og nav-modeller (/modeller).

Kompiler: python kubeflow/trenings_pipeline.py
"""
from kfp import dsl, compiler, kubernetes

IMAGE_TRENING = "nav/trening:lokal"


@dsl.container_component
def eksporter_steg() -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=IMAGE_TRENING,
        command=["python", "skript/eksporter_fra_label_studio.py"],
    )


@dsl.container_component
def konverter_steg() -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=IMAGE_TRENING,
        command=["python", "skript/konverter_til_layoutlmv3.py"],
    )


@dsl.container_component
def finjuster_steg() -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=IMAGE_TRENING,
        command=["python", "skript/finjuster.py"],
    )


def _konfigurer(task: dsl.PipelineTask) -> dsl.PipelineTask:
    task.set_caching_options(False)
    kubernetes.set_image_pull_policy(task, "IfNotPresent")
    kubernetes.mount_pvc(task, pvc_name="nav-data", mount_path="/data")
    kubernetes.mount_pvc(task, pvc_name="nav-modeller", mount_path="/modeller")
    task.set_env_variable("FINJUSTERING_STI", "/data/finjustering")
    task.set_env_variable("MODELLER_STI", "/modeller")
    task.set_env_variable("LABEL_STUDIO_URL", "http://label-studio:8080")
    return task


@dsl.pipeline(
    name="nav-trenings-pipeline",
    description="Label Studio-korreksjoner → LayoutLMv3-finjustering",
)
def trenings_pipeline():
    e = _konfigurer(eksporter_steg())
    k = _konfigurer(konverter_steg())
    f = _konfigurer(finjuster_steg())
    k.after(e)
    f.after(k)


if __name__ == "__main__":
    compiler.Compiler().compile(
        trenings_pipeline,
        package_path="kubeflow/trenings_pipeline.yaml",
    )
    print("Kompilert: kubeflow/trenings_pipeline.yaml")
