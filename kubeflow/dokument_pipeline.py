"""
Kubeflow-pipeline for dokumentbehandling (kubeflow-modus).

Én pipeline-run per opplastet dokument:
    preprocess → ocr → nlp → routing

Hvert steg kjører tjenester.workers.kfp_steg i riktig worker-image.
All tilstand og alle resultater går via Postgres (eneste kilde til
sannhet) — stegene utveksler ingen data seg imellom.

Forutsetninger i clusteret (kubeflow-namespace, se k8s/):
  - Secret  nav-hemmeligheter (POSTGRES_URL)
  - PVC     nav-data      (delte dokumenter, /data)
  - PVC     nav-modeller  (AI-modeller, /modeller)

Kompiler: python kubeflow/dokument_pipeline.py
"""
from kfp import dsl, compiler, kubernetes

IMAGE_LAG0 = "nav/lag0:lokal"
IMAGE_LAG1 = "nav/lag1:lokal"
IMAGE_LAG2 = "nav/lag2:lokal"
IMAGE_LAG3 = "nav/lag3:lokal"


def _steg_spec(image: str, steg: str, job_id: str) -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=image,
        command=["python", "-m", "tjenester.workers.kfp_steg"],
        args=["--steg", steg, "--job-id", job_id],
    )


@dsl.container_component
def preprocess_steg(job_id: str) -> dsl.ContainerSpec:
    return _steg_spec(IMAGE_LAG0, "preprocess", job_id)


@dsl.container_component
def ocr_steg(job_id: str) -> dsl.ContainerSpec:
    return _steg_spec(IMAGE_LAG1, "ocr", job_id)


@dsl.container_component
def nlp_steg(job_id: str) -> dsl.ContainerSpec:
    return _steg_spec(IMAGE_LAG2, "nlp", job_id)


@dsl.container_component
def routing_steg(job_id: str) -> dsl.ContainerSpec:
    return _steg_spec(IMAGE_LAG3, "routing", job_id)


def _konfigurer(task: dsl.PipelineTask, med_modeller: bool = False) -> dsl.PipelineTask:
    task.set_caching_options(False)
    kubernetes.set_image_pull_policy(task, "IfNotPresent")
    kubernetes.mount_pvc(task, pvc_name="nav-data", mount_path="/data")
    if med_modeller:
        kubernetes.mount_pvc(task, pvc_name="nav-modeller", mount_path="/modeller")
    kubernetes.use_secret_as_env(
        task,
        secret_name="nav-hemmeligheter",
        secret_key_to_env={"POSTGRES_URL": "POSTGRES_URL"},
    )
    # Tjenestene kjører i samme namespace som pipeline-podene,
    # så standard-DNS (redis, sok, label-studio) fungerer direkte.
    return task


@dsl.pipeline(
    name="nav-dokument-pipeline",
    description="Preprocess → OCR → NLP → Routing for ett NAV-dokument",
)
def dokument_pipeline(job_id: str):
    p = _konfigurer(preprocess_steg(job_id=job_id))
    o = _konfigurer(ocr_steg(job_id=job_id), med_modeller=True)
    n = _konfigurer(nlp_steg(job_id=job_id), med_modeller=True)
    r = _konfigurer(routing_steg(job_id=job_id))
    o.after(p)
    n.after(o)
    r.after(n)


if __name__ == "__main__":
    compiler.Compiler().compile(
        dokument_pipeline,
        package_path="kubeflow/dokument_pipeline.yaml",
    )
    print("Kompilert: kubeflow/dokument_pipeline.yaml")
