import re
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
EXPRESSION_ON_ATTRIBUTE = re.compile(
    r"(?:'[^']*\bon[a-z]+\s*=|\"[^\"]*\bon[a-z]+\s*=|`[^`]*\bon[a-z]+\s*=)",
    re.IGNORECASE | re.DOTALL,
)
DYNAMIC_ON_ASSIGNMENT = re.compile(
    r"(?:\.|\[\s*['\"])(on[a-z]+)(?:['\"]\s*\])?\s*"
    r"(?:\|\||&&|\?\?|>>>|>>|<<|\*\*|[+\-*/%&|^])?=(?!=|>)",
    re.IGNORECASE,
)
SETATTRIBUTE_ON_HANDLER = re.compile(
    r"\.setAttribute\s*\(\s*['\"]on[a-z]+['\"]", re.IGNORECASE
)


class EventAttributeParser(HTMLParser):
    def __init__(self, *, parse_embedded: bool = True):
        super().__init__(convert_charrefs=False)
        self.parse_embedded = parse_embedded
        self.attributes = []

    def handle_starttag(self, _tag, attrs):
        self.attributes.extend(name for name, _value in attrs if name.casefold().startswith("on"))

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        if self.parse_embedded and "<" in data:
            parser = EventAttributeParser(parse_embedded=False)
            parser.feed(data)
            self.attributes.extend(parser.attributes)


def extract_event_attributes(source: str) -> list[str]:
    parser = EventAttributeParser()
    parser.feed(source)
    return parser.attributes


def skip_template(source: str, index: int) -> int:
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == "`":
            return index + 1
        elif source[index : index + 2] == "${":
            index = skip_expression(source, index + 2)
        else:
            index += 1
    return index


def skip_expression(source: str, index: int) -> int:
    depth = 1
    quote = None
    escaped = False
    while index < len(source) and depth:
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "`":
            index = skip_template(source, index)
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return index


def scan_template(source: str, index: int) -> tuple[bool, int]:
    index += 1
    in_tag = False
    markup_quote = None
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "`":
            return False, index + 1
        if source[index : index + 2] == "${":
            expression_start = index + 2
            index = skip_expression(source, expression_start)
            expression = source[expression_start : index - 1]
            if in_tag and markup_quote is None and EXPRESSION_ON_ATTRIBUTE.search(expression):
                return True, index
            continue
        char = source[index]
        if markup_quote:
            if char == markup_quote:
                markup_quote = None
        elif in_tag and char in "'\"":
            markup_quote = char
        elif char == "<" and index + 1 < len(source) and source[index + 1].isalpha():
            in_tag = True
        elif char == ">":
            in_tag = False
        index += 1
    return False, index


def template_expression_emits_event_attribute(source: str) -> bool:
    index = 0
    while index < len(source):
        if source[index] != "`":
            index += 1
            continue
        found, index = scan_template(source, index)
        if found:
            return True
    return False


def event_policy_violations(source: str) -> set[str]:
    violations = set()
    template_expression_attribute = template_expression_emits_event_attribute(source)
    if extract_event_attributes(source) or template_expression_attribute:
        violations.add("static-or-template-on-attribute")
    if DYNAMIC_ON_ASSIGNMENT.search(source):
        violations.add("dynamic-on-assignment")
    if SETATTRIBUTE_ON_HANDLER.search(source):
        violations.add("setAttribute-on-handler")
    return violations


def scan_frontend() -> dict[str, set[str]]:
    return {
        path.relative_to(ROOT).as_posix(): violations
        for path in sorted(FRONTEND.rglob("*"))
        if path.suffix in {".html", ".js"}
        if (violations := event_policy_violations(path.read_text()))
    }


def test_global_frontend_event_policy():
    samples = {
        '<button onclick="run()">': "static-or-template-on-attribute",
        '<button title="1 > 0" onclick="run()">': "static-or-template-on-attribute",
        'const html = `<button onsubmit="run()">`;': "static-or-template-on-attribute",
        'const html = `<div data-x="${x > 0}" onclick="run()">`;': "static-or-template-on-attribute",
        'const html = `<button title="1 > 0" onclick="run()">`;': "static-or-template-on-attribute",
        'const html = `<button ${disabled ? \'onclick="run()"\' : \'\'}>`;': "static-or-template-on-attribute",
        'const html = `<button ${disabled ? `onclick="run()"` : \'\'}>`;': "static-or-template-on-attribute",
        "select.onchange = run;": "dynamic-on-assignment",
        "node.setAttribute('onclick', 'run()');": "setAttribute-on-handler",
    }
    assert all(expected in event_policy_violations(source) for source, expected in samples.items())
    assert event_policy_violations("node.onclick === null; node['onsubmit'] == null;") == set()
    assert all(
        "dynamic-on-assignment" in event_policy_violations(source)
        for source in ("node.onclick ||= run;", "node['onsubmit'] ??= run;", "node.onchange += run;")
    )
    assert event_policy_violations("const label = `oncall=true`; const other = `onclick = docs`; ") == set()
    assert event_policy_violations("const html = `<div>${enabled ? 'oncall=true' : ''}</div>`;") == set()
    assert event_policy_violations("const html = `<p>${show ? 'onclick = documentation' : ''}</p>`;") == set()
    assert event_policy_violations("const html = `<div title=\"${show ? 'onclick = documentation' : ''}\">x</div>`;") == set()
    assert event_policy_violations("const text = `1 < 2 ${show ? 'onclick = documentation' : ''}`;") == set()
    assert scan_frontend() == {}


def test_login_form_preserves_submit_behavior_and_blocks_duplicates():
    harness = textwrap.dedent(
        r"""
        const assert=require('node:assert/strict');
        const fs=require('node:fs');
        const vm=require('node:vm');
        const html=fs.readFileSync('frontend/login.html','utf8');
        assert.match(html,/<form\b[^>]*id="login-form"/i);
        assert.match(html,/<button\b[^>]*type="submit"/i);
        assert.doesNotMatch(html,/\bonclick\s*=/i);
        const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
        const source=scripts.at(-1)[1];

        function page(){
          const listeners={};
          let lastPrevented=false;
          const form={
            addEventListener(type,handler){listeners[type]=handler},
            requestSubmit(trigger){
              lastPrevented=false;
              return listeners.submit({preventDefault(){lastPrevented=true},submitter:button,trigger});
            },
          };
          const button={disabled:false,click(){return form.requestSubmit('click')}};
          const password={value:'secret',pressEnter(){return form.requestSubmit('enter')}};
          const elements={
            'login-form':form,username:{value:' boss '},password,err:{innerText:''},
            'login-submit':button,
          };
          let resolveFetch,fetchCalls=0;
          const context={
            document:{getElementById:id=>elements[id]},
            location:{href:'/login.html'},
            fetch(){fetchCalls+=1;return new Promise(resolve=>{resolveFetch=resolve})},
          };
          vm.createContext(context);vm.runInContext(source,context);
          return {
            context,elements,listeners,
            resolve(response){resolveFetch(response)},
            get fetchCalls(){return fetchCalls},
            get lastPrevented(){return lastPrevented},
          };
        }

        async function submit(view,trigger,response){
          const pending=trigger==='click'
            ? view.elements['login-submit'].click()
            : view.elements.password.pressEnter();
          assert.equal(view.lastPrevented,true,trigger);
          assert.equal(view.elements['login-submit'].disabled,true,trigger);
          view.resolve(response);
          await pending;
        }

        (async()=>{
          const click=page();
          const first=click.elements['login-submit'].click();
          assert.equal(click.lastPrevented,true);
          assert.equal(click.fetchCalls,1);
          assert.equal(click.elements['login-submit'].disabled,true);
          await click.elements['login-form'].requestSubmit('duplicate');
          assert.equal(click.fetchCalls,1,'duplicate submit');
          click.resolve({ok:true,json:async()=>({})});await first;
          assert.equal(click.context.location.href,'/index.html');

          const enter=page();
          await submit(enter,'enter',{ok:false,json:async()=>({detail:'凭据错误'})});
          assert.equal(enter.elements.err.innerText,'凭据错误');
          assert.equal(enter.elements['login-submit'].disabled,false);
          assert.equal(enter.fetchCalls,1);
        })().catch(error=>{console.error(error);process.exit(1)});
        """
    )
    subprocess.run(["node", "-e", harness], cwd=ROOT, check=True)


def test_alpha_events_bind_once_and_preserve_change_and_submit_behavior():
    harness = textwrap.dedent(
        r"""
        const assert=require('node:assert/strict');
        const fs=require('node:fs');
        const vm=require('node:vm');
        (async()=>{
        let source=fs.readFileSync('frontend/alpha-workflow.js','utf8');
        source=source.replace(
          /\n\}\)\(\);\s*$/,
          '\n  globalThis.__alphaTest={bindListEvents,bindDetailEvents,renderScenarios,handleAction,setDetail(value){detail=value}};\n})();'
        );

        function element(extra={}){
          const listeners={};
          return Object.assign({
            listeners,disabled:false,hidden:false,value:'',textContent:'',innerText:'',
            addEventListener(type,handler){(listeners[type]??=[]).push(handler)},
            showModal(){this.open=true},close(){this.open=false},
          },extra);
        }
        const refresh=element();
        const scenario=element({selectedOptions:[{dataset:{input:'默认研究目标'}}]});
        const workflow=element();
        const startForm=element();
        const reasonForm=element();
        const reasonDialog=element();
        const reasonConfirm=element();
        const nodes={
          'scenario-select':scenario,'workflow-input':workflow,'start-form':startForm,
          'reason-form':reasonForm,'reason-dialog':reasonDialog,'reason-confirm':reasonConfirm,
          'reason-title':element(),'reason-help':element(),'reason-input':element({value:'原因'}),
          'page-message':element(),
        };
        const requests=[];
        const context={
          document:{
            body:{dataset:{page:''}},getElementById:id=>nodes[id]??element(),
            querySelector:selector=>selector==='[data-action="refresh"]'?refresh:element(),
          },
          location:{href:'',search:''},history:{replaceState(){}},URLSearchParams,
          Intl,Date,encodeURIComponent,
          fetch:async(url,options={})=>{
            requests.push({url,options});
            return {ok:false,status:400,json:async()=>({detail:'预期测试拒绝'})};
          },
        };
        vm.createContext(context);vm.runInContext(source,context);
        const api=context.__alphaTest;

        api.bindListEvents();api.bindListEvents();
        assert.equal(scenario.listeners.change.length,1,'scenario duplicate binding');
        assert.equal(startForm.listeners.submit.length,1,'start form duplicate binding');
        api.renderScenarios([{enabled:true,scenario_code:'s1',default_input_text:'默认研究目标',title:'场景'}]);
        scenario.listeners.change[0]();
        assert.equal(workflow.value,'默认研究目标','scenario change behavior');

        api.bindDetailEvents('run-1');api.bindDetailEvents('run-1');
        assert.equal(reasonForm.listeners.submit.length,1,'reason form duplicate binding');
        api.setDetail({run:{run_id:'run-1'}});
        api.handleAction('recover');
        assert.equal(reasonDialog.open,true);
        let prevented=false;
        await reasonForm.listeners.submit[0]({preventDefault(){prevented=true},submitter:{value:'confirm'}});
        assert.equal(prevented,true);
        assert.equal(requests.length,1);
        assert.match(requests[0].url,/\/runs\/run-1\/recover$/);
        assert.equal(requests[0].options.method,'POST');
        assert.equal(reasonConfirm.disabled,false);
        })().catch(error=>{console.error(error);process.exit(1)});
        """
    )
    subprocess.run(["node", "-e", harness], cwd=ROOT, check=True)
