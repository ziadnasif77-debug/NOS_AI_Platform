import json
import threading
from flask import Flask, render_template, Response, stream_with_context
from pipeline import kjor_pipeline, FASER

app = Flask(__name__, template_folder="maler")


def send_hendelse_fabrikk(ko):
    def send_hendelse(fase_id, status, melding, fremdrift):
        data = json.dumps({
            "fase": fase_id,
            "status": status,
            "melding": melding,
            "fremdrift": fremdrift
        }, ensure_ascii=False)
        ko.append(f"data: {data}\n\n")
    return send_hendelse


@app.route("/")
def indeks():
    return render_template("indeks.html", faser=FASER)


@app.route("/pipeline-start")
def pipeline_start():
    hendelse_buffer = []

    def generer():
        send_hendelse = send_hendelse_fabrikk(hendelse_buffer)
        trad = threading.Thread(target=kjor_pipeline, args=(send_hendelse,))
        trad.daemon = True
        trad.start()

        ferdig = False
        while not ferdig:
            while hendelse_buffer:
                melding = hendelse_buffer.pop(0)
                yield melding
                if '"fase": "__ferdig__"' in melding:
                    ferdig = True
                    break
            if not ferdig:
                import time
                time.sleep(0.1)

    return Response(
        stream_with_context(generer()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
