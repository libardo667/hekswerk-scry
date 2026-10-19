"""Additional Scry review regressions (expected to fail on the reviewed archive).

Run: python review_regression_tests.py --repo /path/to/hekswerk-scry -v
All tests are offline. No real Lean or AI provider is used. The subprocess fault test
runs a clearly synthetic executable to exercise the actual runner protocol.
"""
from __future__ import annotations
import argparse
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_parser=argparse.ArgumentParser(add_help=False)
_parser.add_argument('--repo',type=pathlib.Path,default=pathlib.Path('.'))
_args,_remaining=_parser.parse_known_args()
ROOT=_args.repo.resolve()
if not (ROOT / 'src' / 'hekswerk_scry').is_dir():
    _parser.error('--repo must name the extracted Hekswerk Scry repository root')
sys.path.insert(0,str(ROOT/'src'))
from hekswerk_scry.ai.audit import audit_challenge
from hekswerk_scry.ai.benchmark import score_plant, CAUGHT, EarlierResult, reusable
from hekswerk_scry.ai.statement_tools import StatementToolbox, VerdictRow
from hekswerk_scry.lean.openai_math import Challenge
from hekswerk_scry.lean.runner import check_file
from hekswerk_scry.lean.statement import read_statement, report_from_json
from hekswerk_scry.lean.workspace import LeanWorkspace
from hekswerk_scry.models.receipts import LeanRunEvidence
from hekswerk_scry.files import save_outline
from hekswerk_scry.web.server import Library, Source
sys.path.insert(0,str(ROOT))
from tests.test_outline import example_outline

EVIDENCE=LeanRunEvidence(('review-fixture-only',),0,False,'0'*64,0.01)

def workspace(root: pathlib.Path) -> LeanWorkspace:
    (root/'lean-toolchain').write_text('leanprover/lean4:v4.34.1\n')
    (root/'lake-manifest.json').write_text('{"packages":[]}')
    exporter=root/'fixture-exporter'; exporter.write_text('not executable; fixture only')
    return LeanWorkspace(root=root,lake=root/'fake-lake',exporter=exporter,is_scry_project=False)

def sample_report():
    return json.loads((ROOT/'tests/fixtures/statements/probe_honest.json').read_text())

class ReviewRegressions(unittest.TestCase):
    def test_browser_outline_freshness_tracks_underlying_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            outline=example_outline(root)
            path=root/'review.outline.json'
            save_outline(outline,path)
            library=Library([Source('maps',root)])
            token=library.overview()['outlines'][0]['token']
            first=library.outline(token)
            source=root/'Examples'/'Outline.lean'
            source.write_text(source.read_text()+'\n-- source has changed\n')
            second=library.outline(token)
            self.assertNotEqual(first['changed_files'],second['changed_files'],
                f'Changed the Lean source, but browser freshness stayed {second["changed_files"]!r}.')

    def test_imported_definition_edit_invalidates_statement_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); ws=workspace(root)
            source=root/'Claim.lean'; source.write_text('import Meaning\ntheorem t : Flag := sorry\n')
            dependency=root/'Meaning.lean'; dependency.write_text('def Flag : Prop := True\n')
            data=sample_report()
            with patch.object(LeanWorkspace,'build_imports') as build, patch(
                'hekswerk_scry.lean.statement.run_exporter',return_value=(data,EVIDENCE)
            ) as exporter:
                read_statement(ws,source,data['theorem'])
                dependency.write_text('def Flag : Prop := False\n')
                second=read_statement(ws,source,data['theorem'])
            self.assertEqual(exporter.call_count,2,
                f'Stale report reused: exporter calls={exporter.call_count}, build calls={build.call_count}, reused_from={second.reused_from!r}')

    def test_manifest_edit_invalidates_statement_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); ws=workspace(root)
            source=root/'Claim.lean'; source.write_text('theorem t : True := trivial\n')
            data=sample_report()
            with patch.object(LeanWorkspace,'build_imports'), patch(
                'hekswerk_scry.lean.statement.run_exporter',return_value=(data,EVIDENCE)
            ) as exporter:
                read_statement(ws,source,data['theorem'])
                (root/'lake-manifest.json').write_text('{"packages":[{"name":"mathlib","rev":"changed"}]}')
                second=read_statement(ws,source,data['theorem'])
            self.assertEqual(exporter.call_count,2,f'Manifest changed, but cached report reused: {second.reused_from!r}')

    def test_failed_process_exit_cannot_produce_passing_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); ws=workspace(root)
            source=root/'Claim.lean'; source.write_text('theorem t : True := trivial\n')
            message={'severity':'information','pos':{'line':3,'column':0},
                     'data':"'t' does not depend on any axioms"}
            ws.lake.write_text('#!'+sys.executable+'\nimport sys\nprint('+repr(json.dumps(message))+')\nsys.exit(23)\n')
            ws.lake.chmod(0o700)
            checked=check_file(ws,source,'t',fresh=True)
            self.assertFalse(checked.passed,
                f'Runner accepted synthetic failed process: exit={checked.receipt.lean_run.exit_code}, passed={checked.passed}, summary={checked.receipt.summary}')

    def test_unchecked_comparator_does_not_become_proved_in_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); ws=workspace(root)
            source=root/'Challenge.lean'; source.write_text('theorem t : True := sorry\n')
            data=sample_report(); data['axioms']=['sorryAx']; data['theorem']='t'
            report=report_from_json(data,'Challenge.lean',EVIDENCE)
            item=Challenge('Example',source,'Missing.Solution',root/'Missing/Solution.lean',('t',),())
            with patch('hekswerk_scry.ai.audit.openai_math.challenge',return_value=item), patch(
                'hekswerk_scry.ai.audit.workspace_for_file',return_value=ws), patch(
                'hekswerk_scry.ai.audit.paper_files_for',return_value=((),[])), patch(
                'hekswerk_scry.ai.audit.read_statement',return_value=report), patch(
                'hekswerk_scry.ai.audit.run_audit') as run:
                audit_challenge(object(),'Example')
            prompt=run.call_args.args[2]
            self.assertNotIn('Lean has checked a proof of it',prompt,
                'No solution file exists and the report has sorryAx, but the prompt asserts a checked proof.')

    def test_unclear_is_not_a_successful_detection(self):
        row=VerdictRow('Unknown','claim','I cannot establish correspondence','unclear',False,(10,10),('E1',))
        score=score_plant([row],(10,10))
        self.assertNotEqual(score,CAUGHT,f'An explicitly unresolved row was scored {score!r}.')

    def test_overlapping_uncertainty_does_not_hide_false_reassurance(self):
        rows=[VerdictRow('Mistaken reassurance','claim','matches','matches',True,(10,10),('E1',)),
              VerdictRow('Uncertainty','claim','not sure','unclear',False,(10,10),('E1',))]
        score=score_plant(rows,(10,10))
        self.assertNotEqual(score,CAUGHT,f'Contradictory matches + unclear rows were scored {score!r}.')

    def test_duplicate_paper_paths_have_unique_readable_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); ws=workspace(root)
            source=root/'Statement.lean'; source.write_text('theorem t : True := sorry\n')
            papers=[]
            for name,content in [('PaperA','FIRST PAPER'),('PaperB','SECOND PAPER')]:
                p=root/name/'build'/'main.tex'; p.parent.mkdir(parents=True); p.write_text(content+'\n'); papers.append(p)
            toolbox=StatementToolbox(ws,source,'Example',{},papers)
            labels=[toolbox.label(p) for p in papers]
            read=toolbox.run('read_paper',{'file':labels[1],'first_line':1,'last_line':1})
            self.assertIn('SECOND PAPER',read.result,
                f'Asked to read the second paper using its advertised label. Labels={labels}; returned {read.result!r}')

    def test_probe_with_sorry_axiom_is_not_treated_as_math_evidence(self):
        data=copy.deepcopy(sample_report())
        data['probes']={'vacuity':{'found':True,'tactic':'simp_all','axioms':['sorryAx']},
                        'triviality':{'found':False,'note':'not found'}}
        try:
            report=report_from_json(data,'Fixture.lean',EVIDENCE)
        except (ValueError,RuntimeError):
            return  # Fail-closed rejection is also acceptable.
        self.assertFalse(report.red_flags,
            f'A sorry-dependent probe became a claimed contradiction: {report.red_flags[0].headline}')

    def test_interrupted_benchmark_run_not_silently_reused_as_complete(self):
        earlier=EarlierResult('same-source',[],0.1,True)
        self.assertFalse(reusable(earlier,'same-source'),
            'An audit that hit its round limit is reused by the same success path as a complete audit.')

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0],*_remaining])
