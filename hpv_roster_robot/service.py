from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Any, Mapping
from hpv_roster_robot.runtime import DomainError, ProcessingContext, SQLiteLedger, fingerprint, normalize_text
from hpv_roster_robot.roster.intake import build_processor as intake_factory
from hpv_roster_robot.eligibility.age_window import build_processor as age_window_factory
from hpv_roster_robot.doses.schedule import build_processor as schedule_factory
from hpv_roster_robot.portal.session_machine import build_processor as session_machine_factory
from hpv_roster_robot.receipts.reconcile import build_processor as reconcile_factory
from hpv_roster_robot.exceptions.work_items import build_processor as work_items_factory
from hpv_roster_robot.audit.action_trail import build_processor as action_trail_factory
from hpv_roster_robot.closure.batch_close import build_processor as batch_close_factory

PROCESSOR_FACTORIES = [intake_factory, age_window_factory, schedule_factory, session_machine_factory, reconcile_factory, work_items_factory, action_trail_factory, batch_close_factory]

class ApplicationService:
    def __init__(self, database: str | Path):
        self.ledger=SQLiteLedger(database)
        self.processors=[factory() for factory in PROCESSOR_FACTORIES]

    def validate_input(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(record, Mapping): raise DomainError("record must be object")
        result=dict(record)
        result["case_id"]=normalize_text(result.get("case_id"),"case_id",96)
        if not result["case_id"]: raise DomainError("case_id is required")
        result.setdefault("subject_id",result["case_id"])
        result.setdefault("category","screening")
        result.setdefault("region","synthetic-region")
        result.setdefault("event_date","2026-11-11")
        result.setdefault("status","new")
        result.setdefault("count",1)
        result.setdefault("total",1)
        result.setdefault("attributes",{"source":"synthetic"})
        result.setdefault("tags",["offline","fixture"])
        result.setdefault("source_system","local-fixture")
        result.setdefault("revision",0)
        return result

    def execute(self, record: Mapping[str, Any], request_key: str | None=None) -> dict[str, Any]:
        normalized=self.validate_input(record)
        normalized=self.architecture_preflight(normalized)
        key=request_key or fingerprint(normalized)
        recalled=self.ledger.recalled(key)
        if recalled is not None: return recalled | {"replayed":True}
        ctx=ProcessingContext(uuid.uuid4().hex,normalized["case_id"],normalized)
        ctx.emit("received","run_started",project='hpv_roster_robot')
        try:
            for processor in self.architecture_plan(ctx):
                processor.process(ctx)
                self.ledger.save(ctx)
        except Exception as exc:
            self.ledger.dead_letter(ctx,ctx.state,str(exc),normalized)
            raise
        self.architecture_finalize(ctx)
        ctx.advance("completed")
        self.ledger.save(ctx)
        response={"project":'hpv_roster_robot',"run_id":ctx.run_id,"case_id":ctx.case_id,"state":ctx.state,
                  "revision":ctx.revision,"flags":ctx.flags,"metrics":ctx.metrics,"evidence_count":len(ctx.evidence),
                  "event_count":len(ctx.events),"payload":ctx.payload,"replayed":False}
        self.ledger.remember(key,ctx.run_id,response)
        return response

    def architecture_preflight(self, record):
        record=dict(record)
        record["robot_session"]={"cursor":0,"actions":[],"compensations":[],"portal":"offline-simulator"}
        birth=record.get("attributes",{}).get("birth_year",2013)
        record["eligible_year_window"]=2011 <= int(birth) <= 2014
        return record

    def architecture_plan(self, ctx):
        plan=[]
        for processor in self.processors:
            ctx.payload["robot_session"]["actions"].append({"step":processor.stage,"status":"planned"})
            plan.append(processor)
        ctx.emit("robot_saga","session_planned",steps=len(plan))
        return plan

    def architecture_finalize(self, ctx):
        actions=ctx.payload["robot_session"]["actions"]
        for action in actions: action["status"]="acknowledged" if not ctx.flags else "review"
        if ctx.flags: ctx.payload["robot_session"]["compensations"].append("release_portal_lock")
        ctx.payload["robot_session"]["cursor"]=len(actions)
        ctx.emit("robot_saga","session_closed",compensations=ctx.payload["robot_session"]["compensations"])

    def execute_many(self, records: list[Mapping[str, Any]]) -> dict[str, Any]:
        outputs=[]; failures=[]
        for index, record in enumerate(records):
            try: outputs.append(self.execute(record,request_key=f"batch:{index}:{fingerprint(record)}"))
            except Exception as exc: failures.append({"index":index,"error":str(exc)})
        return {"accepted":outputs,"failures":failures,"accepted_count":len(outputs),"failure_count":len(failures)}

def run_fixture(fixture: str | Path, database: str | Path) -> dict[str, Any]:
    data=json.loads(Path(fixture).read_text(encoding="utf-8"))
    service=ApplicationService(database)
    if isinstance(data,list): return service.execute_many(data)
    return service.execute(data)
