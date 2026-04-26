from __future__ import annotations

import os
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .chatbot import (
    answer_question,
    ensure_index,
    retrieve_evidence,
    rt_fetch_reviews_from_url,
    rt_movie_overview,
    rt_search_movies,
)


def _ollama_kwargs() -> dict:
    base_url = (
        os.getenv("OLLAMA_BASE_URL", "").strip()
        or os.getenv("OLLAMA_HOST", "").strip()
        or os.getenv("OLLAMA_URL", "").strip()
    )
    return {"base_url": base_url} if base_url else {}


app = FastAPI(title="Chatbot RAG API", version="1.0.0")


def _agent_tools_spec() -> list[dict[str, Any]]:
    return [
        {
            "name": "rt_search_movies",
            "description": "Search Rotten Tomatoes for movies by query.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
        },
        {
            "name": "rt_describe_movie",
            "description": "Fetch movie overview/synopsis from Rotten Tomatoes page.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
        {
            "name": "rt_fetch_reviews",
            "description": "Fetch Rotten Tomatoes reviews (critic or audience).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "kind": {"type": "string", "enum": ["critic", "audience"]},
                    "top_only": {"type": "boolean"},
                    "verified": {"type": ["boolean", "null"]},
                    "limit": {"type": "integer"},
                },
            },
        },
        {
            "name": "index_url",
            "description": "Ensure the local Chroma index matches the given source URL.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
        {
            "name": "retrieve",
            "description": "Retrieve top-k evidence chunks from the vector DB.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "query": {"type": "string"}, "top_k": {"type": "integer"}},
            },
        },
        {
            "name": "rag_ask",
            "description": "Answer a question using RAG over the indexed reviews.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "question": {"type": "string"}, "top_k": {"type": "integer"}},
            },
        },
    ]


def _agent_execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "rt_search_movies":
        q = (arguments.get("query") or "").strip()
        limit = int(arguments.get("limit") or 10)
        return {"results": rt_search_movies(q, limit=limit)}
    if name == "rt_describe_movie":
        url = str(arguments.get("url") or "").strip()
        return {"overview": rt_movie_overview(url)}
    if name == "rt_fetch_reviews":
        url = str(arguments.get("url") or "").strip()
        kind = str(arguments.get("kind") or "critic")
        top_only = bool(arguments.get("top_only") or False)
        verified = arguments.get("verified", None)
        limit = int(arguments.get("limit") or 50)
        return {
            "reviews": rt_fetch_reviews_from_url(url, kind=kind, top_only=top_only, verified=verified, limit=limit),
        }
    if name == "index_url":
        url = str(arguments.get("url") or "").strip()
        return ensure_index(url)
    if name == "retrieve":
        url = str(arguments.get("url") or "").strip()
        query = str(arguments.get("query") or "").strip()
        top_k = int(arguments.get("top_k") or 8)
        info = ensure_index(url)
        ev = retrieve_evidence(expected_url=info["expected_url"], query=query, top_k=top_k)
        return {"expected_url": info["expected_url"], "evidence": ev}
    if name == "rag_ask":
        url = str(arguments.get("url") or "").strip()
        question = str(arguments.get("question") or "").strip()
        top_k = int(arguments.get("top_k") or 6)
        info = ensure_index(url)
        res = answer_question(expected_url=info["expected_url"], question=question, top_k=top_k)
        return {"expected_url": info["expected_url"], **res}

    raise ValueError(f"Unknown tool: {name}")


class IndexRequest(BaseModel):
    url: str = Field(..., min_length=8, description="Source page URL (e.g. RottenTomatoes movie link).")


class IndexResponse(BaseModel):
    expected_url: str
    reused_vectordb: bool
    scraped: bool
    embedded: bool


class AskRequest(BaseModel):
    url: str = Field(..., min_length=8, description="Source page URL. If changed, index will be rebuilt.")
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(6, ge=1, le=20)


class AskResponse(BaseModel):
    expected_url: str
    answer: str
    evidence: list[dict[str, Any]]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(10, ge=1, le=50)


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]


class DescribeRequest(BaseModel):
    url: str = Field(..., min_length=8)


class DescribeResponse(BaseModel):
    overview: dict[str, Any]


class AgentMessage(BaseModel):
    role: str = Field(..., description="system|user|assistant|tool")
    content: str = Field("", description="Message content")


class AgentRequest(BaseModel):
    messages: list[AgentMessage] = Field(..., min_length=1)
    max_steps: int = Field(6, ge=1, le=12)


class AgentToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class AgentResponse(BaseModel):
    assistant: str
    tool_calls: list[AgentToolCall] = []
    tool_results: list[dict[str, Any]] = []


class RetrieveRequest(BaseModel):
    url: str = Field(..., min_length=8)
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(8, ge=1, le=50)


class RetrieveResponse(BaseModel):
    expected_url: str
    evidence: list[dict[str, Any]]


class ReviewsRequest(BaseModel):
    url: str = Field(..., min_length=8)
    kind: str = Field("critic", description="critic|audience")
    top_only: bool = False
    verified: bool | None = None
    limit: int = Field(50, ge=1, le=500)


class ReviewsResponse(BaseModel):
    reviews: list[dict[str, Any]]


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return """<!doctype html>
<html lang="tr">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Chatbot RAG UI</title>
    <style>
      :root { color-scheme: light dark; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 0; padding: 0; }
      header { padding: 14px 18px; border-bottom: 1px solid rgba(127,127,127,.3); }
      main { padding: 18px; max-width: 1100px; margin: 0 auto; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .card { border: 1px solid rgba(127,127,127,.3); border-radius: 10px; padding: 14px; }
      .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      input, textarea, button, select { font: inherit; }
      input, textarea, select { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid rgba(127,127,127,.35); }
      textarea { min-height: 110px; }
      button { padding: 10px 12px; border-radius: 8px; border: 1px solid rgba(127,127,127,.35); cursor: pointer; }
      button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", monospace; }
      .small { font-size: 12px; opacity: .8; }
      .out { white-space: pre-wrap; border-radius: 8px; border: 1px solid rgba(127,127,127,.25); padding: 10px; min-height: 88px; }
      .pill { display:inline-block; padding: 3px 8px; border: 1px solid rgba(127,127,127,.35); border-radius: 999px; font-size: 12px; }
      .col-span { grid-column: 1 / -1; }
      @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <header>
      <div class="row" style="justify-content:space-between">
        <div>
          <div style="font-weight:700">Chatbot RAG</div>
          <div class="small">RottenTomatoes + Chroma + Ollama</div>
        </div>
        <div class="pill mono" id="health">health: ?</div>
      </div>
    </header>
    <main>
      <div class="card col-span">
        <div class="row">
          <div style="flex: 1 1 520px">
            <label class="small">Seçili URL (RT film linki)</label>
            <input id="currentUrl" class="mono" placeholder="https://www.rottentomatoes.com/m/..." />
          </div>
          <div style="flex: 0 0 auto">
            <label class="small">&nbsp;</label>
            <button id="btnIndex" class="primary">Index</button>
          </div>
          <div style="flex: 0 0 auto">
            <label class="small">&nbsp;</label>
            <button id="btnDescribe">Describe</button>
          </div>
        </div>
        <div class="small" id="indexStatus"></div>
      </div>

      <div class="grid">
        <div class="card">
          <div style="font-weight:700; margin-bottom:8px">Film Ara</div>
          <div class="row">
            <div style="flex: 1 1 auto">
              <input id="searchQuery" placeholder="örn: normal" />
            </div>
            <div style="flex: 0 0 auto">
              <button id="btnSearch" class="primary">Search</button>
            </div>
          </div>
          <div class="small">Sonuçlardan birini seçip URL’i otomatik doldur.</div>
          <select id="searchResults" size="8" style="margin-top:10px"></select>
        </div>

        <div class="card">
          <div style="font-weight:700; margin-bottom:8px">Sor (RAG)</div>
          <label class="small">Soru</label>
          <textarea id="askQuestion" placeholder="Describe the movie / What do critics praise?"></textarea>
          <div class="row" style="margin-top:8px">
            <div style="flex: 0 0 120px">
              <label class="small">top_k</label>
              <input id="askTopK" value="6" />
            </div>
            <div style="flex: 1 1 auto">
              <label class="small">&nbsp;</label>
              <button id="btnAsk" class="primary" style="width:100%">Ask</button>
            </div>
          </div>
          <div class="small" style="margin-top:10px">Cevap</div>
          <div class="out mono" id="askOut"></div>
        </div>

        <div class="card col-span">
          <div style="font-weight:700; margin-bottom:8px">Agent Chat (Toolcalling)</div>
          <div class="small">Agent kendi kendine tool’ları çağırarak ilerler.</div>
          <div class="row" style="margin-top:10px">
            <div style="flex: 1 1 720px">
              <input id="agentInput" placeholder="örn: Search Normal on Rotten Tomatoes and summarize the synopsis." />
            </div>
            <div style="flex: 0 0 auto">
              <button id="btnAgent" class="primary">Run Agent</button>
            </div>
            <div style="flex: 0 0 120px">
              <input id="agentSteps" value="6" title="max_steps" />
            </div>
          </div>
          <div class="small" style="margin-top:10px">Agent output</div>
          <div class="out mono" id="agentOut"></div>
        </div>
      </div>
    </main>

    <script>
      const $ = (id) => document.getElementById(id);
      async function api(path, body) {
        const res = await fetch(path, {
          method: \"POST\",
          headers: { \"content-type\": \"application/json\" },
          body: JSON.stringify(body),
        });
        const txt = await res.text();
        let data;
        try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
        if (!res.ok) throw new Error((data && data.detail) ? data.detail : txt);
        return data;
      }

      async function refreshHealth() {
        try {
          const res = await fetch(\"/healthz\");
          $(\"health\").textContent = \"health: \" + (res.ok ? \"ok\" : \"bad\");
        } catch {
          $(\"health\").textContent = \"health: down\";
        }
      }

      $(\"btnSearch\").onclick = async () => {
        const q = $(\"searchQuery\").value.trim();
        if (!q) return;
        $(\"searchResults\").innerHTML = \"\";
        try {
          const data = await api(\"/v1/search\", { query: q, limit: 10 });
          for (const r of (data.results || [])) {
            const opt = document.createElement(\"option\");
            const parts = [];
            if (r.title) parts.push(r.title);
            if (r.year) parts.push(r.year);
            if (r.tomatometer_score) parts.push(\"TM=\" + r.tomatometer_score + \"%\");
            opt.textContent = parts.join(\" | \") + (r.url ? (\" | \" + r.url) : \"\");
            opt.value = r.url || \"\";
            $(\"searchResults\").appendChild(opt);
          }
        } catch (e) {
          alert(\"search error: \" + e.message);
        }
      };

      $(\"searchResults\").ondblclick = () => {
        const v = $(\"searchResults\").value;
        if (v) $(\"currentUrl\").value = v;
      };

      $(\"btnDescribe\").onclick = async () => {
        const url = $(\"currentUrl\").value.trim();
        if (!url) return alert(\"URL boş\");
        try {
          const data = await api(\"/v1/describe\", { url });
          $(\"askOut\").textContent = JSON.stringify(data.overview || {}, null, 2);
        } catch (e) {
          alert(\"describe error: \" + e.message);
        }
      };

      $(\"btnIndex\").onclick = async () => {
        const url = $(\"currentUrl\").value.trim();
        if (!url) return alert(\"URL boş\");
        $(\"indexStatus\").textContent = \"Indexing...\";
        try {
          const data = await api(\"/v1/index\", { url });
          $(\"indexStatus\").textContent = \"ok: \" + JSON.stringify(data);
        } catch (e) {
          $(\"indexStatus\").textContent = \"error: \" + e.message;
        }
      };

      $(\"btnAsk\").onclick = async () => {
        const url = $(\"currentUrl\").value.trim();
        const question = $(\"askQuestion\").value.trim();
        const top_k = parseInt(($(\"askTopK\").value || \"6\").trim(), 10) || 6;
        if (!url) return alert(\"URL boş\");
        if (!question) return alert(\"Soru boş\");
        $(\"askOut\").textContent = \"Running...\";
        try {
          const data = await api(\"/v1/ask\", { url, question, top_k });
          $(\"askOut\").textContent = (data.answer || \"\") + \"\\n\\nEVIDENCE:\\n\" + JSON.stringify(data.evidence || [], null, 2);
        } catch (e) {
          $(\"askOut\").textContent = \"error: \" + e.message;
        }
      };

      $(\"btnAgent\").onclick = async () => {
        const input = $(\"agentInput\").value.trim();
        const max_steps = parseInt(($(\"agentSteps\").value || \"6\").trim(), 10) || 6;
        if (!input) return;
        $(\"agentOut\").textContent = \"Running agent...\";
        try {
          const data = await api(\"/v1/agent/chat\", { messages: [{ role: \"user\", content: input }], max_steps });
          $(\"agentOut\").textContent =
            (data.assistant || \"\") + \"\\n\\nTOOL_CALLS:\\n\" + JSON.stringify(data.tool_calls || [], null, 2) +
            \"\\n\\nTOOL_RESULTS:\\n\" + JSON.stringify(data.tool_results || [], null, 2);
        } catch (e) {
          $(\"agentOut\").textContent = \"error: \" + e.message;
        }
      };

      refreshHealth();
      setInterval(refreshHealth, 5000);
    </script>
  </body>
</html>"""


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.post("/v1/index", response_model=IndexResponse)
def index(req: IndexRequest) -> IndexResponse:
    try:
        info = ensure_index(req.url)
        return IndexResponse(**info)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    try:
        info = ensure_index(req.url)
        result = answer_question(expected_url=info["expected_url"], question=req.question, top_k=req.top_k)
        return AskResponse(expected_url=info["expected_url"], answer=result["answer"], evidence=result["evidence"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    try:
        results = rt_search_movies(req.query, limit=req.limit)
        return SearchResponse(results=results)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/describe", response_model=DescribeResponse)
def describe(req: DescribeRequest) -> DescribeResponse:
    try:
        ov = rt_movie_overview(req.url)
        return DescribeResponse(overview=ov)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest) -> RetrieveResponse:
    try:
        info = ensure_index(req.url)
        ev = retrieve_evidence(expected_url=info["expected_url"], query=req.query, top_k=req.top_k)
        return RetrieveResponse(expected_url=info["expected_url"], evidence=ev)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/v1/rt/reviews", response_model=ReviewsResponse)
def rt_reviews(req: ReviewsRequest) -> ReviewsResponse:
    try:
        reviews = rt_fetch_reviews_from_url(
            req.url,
            kind=req.kind,
            top_only=req.top_only,
            verified=req.verified,
            limit=req.limit,
        )
        return ReviewsResponse(reviews=reviews)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/v1/agent/tools")
def agent_tools() -> dict[str, Any]:
    return {"tools": _agent_tools_spec()}


@app.post("/v1/agent/chat", response_model=AgentResponse)
def agent_chat(req: AgentRequest) -> AgentResponse:
    """
    Lightweight toolcalling loop:
    - LLM must output JSON: {"tool_calls":[{"name":"...","arguments":{...}}, ...]} or {"final":"..."}.
    - Server executes tools and feeds results back until final or max_steps.
    """

    from langchain_ollama import ChatOllama

    tools_json = json.dumps(_agent_tools_spec(), ensure_ascii=False)
    system = (
        "You are an agent that can call tools.\n"
        "Return ONLY valid JSON.\n"
        "Output either:\n"
        '1) {"tool_calls":[{"name":"tool","arguments":{...}}, ...]}\n'
        'or 2) {"final":"..."}\n'
        "Do not add extra keys.\n"
        "Available tools JSON:\n"
        f"{tools_json}\n"
    )

    # Convert messages to plain text conversation, then ask model to propose tool calls.
    transcript_lines: list[str] = [f"SYSTEM:\n{system}"]
    for m in req.messages:
        transcript_lines.append(f"{m.role.upper()}:\n{m.content}")
    transcript = "\n\n".join(transcript_lines).strip()

    llm = ChatOllama(model=os.getenv("OLLAMA_LLM_MODEL", "llama3.2:1b"), temperature=0, **_ollama_kwargs())

    tool_results: list[dict[str, Any]] = []
    last_tool_calls: list[AgentToolCall] = []

    for _step in range(int(req.max_steps or 6)):
        raw = llm.invoke(transcript)
        text = (getattr(raw, "content", None) or str(raw)).strip()

        try:
            parsed = json.loads(text)
        except Exception:
            # If the model fails to return JSON, stop and return the raw content.
            return AgentResponse(assistant=text, tool_calls=[], tool_results=tool_results)

        if isinstance(parsed, dict) and "final" in parsed:
            return AgentResponse(assistant=str(parsed.get("final") or ""), tool_calls=last_tool_calls, tool_results=tool_results)

        calls = parsed.get("tool_calls") if isinstance(parsed, dict) else None
        if not isinstance(calls, list) or not calls:
            return AgentResponse(assistant=text, tool_calls=[], tool_results=tool_results)

        last_tool_calls = []
        for c in calls:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
            last_tool_calls.append(AgentToolCall(name=name, arguments=args))

        # Execute tools
        step_results: list[dict[str, Any]] = []
        for call in last_tool_calls:
            try:
                res = _agent_execute_tool(call.name, call.arguments)
                step_results.append({"tool": call.name, "ok": True, "result": res})
            except Exception as e:
                step_results.append({"tool": call.name, "ok": False, "error": str(e)})

        tool_results.extend(step_results)

        # Append tool results to transcript and iterate
        transcript += "\n\nTOOL_RESULTS:\n" + json.dumps(step_results, ensure_ascii=False)

    return AgentResponse(
        assistant="Max steps reached without a final answer.",
        tool_calls=last_tool_calls,
        tool_results=tool_results,
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("chatbot.api_server:app", host=host, port=port, reload=True)
