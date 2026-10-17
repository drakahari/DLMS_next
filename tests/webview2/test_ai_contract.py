"""Closed Local producer metadata; no browser/network/profile access."""
import base64
import json

import pytest
from flask import Flask, request
from desktop.webview2_ai_contract import contract, install, HEADER, REQUEST_HEADER, PROVIDERS

TAG='a'*32
CONFIG={'ai_helper_enabled':True,'ai_provider':'chatgpt','ai_custom_url':'https://custom.invalid/ai'}

def decoded(value):return json.loads(base64.b64decode(value))

@pytest.mark.parametrize('path,actions',[
    ('/quizzes/Synthetic 日本語 quiz.html',['study-review']),
    ('/review',['review-single','review-selected']),('/review.html',['review-single','review-selected']),
    ('/study-packs/ai-builder',['study-pack']),('/law/create',['law-prompt']),
    ('/certifications/matches',['cert-combined','cert-manual']),
    ('/certifications/'+'1'*32+'/ai',['cert-combined','cert-manual'])])
@pytest.mark.parametrize('provider',list(PROVIDERS)+['local'])
def test_exact_producer_actions_and_provider(path,actions,provider):
    value=decoded(contract(path,'POST',{'ai_provider':provider},CONFIG|{'ai_provider':provider},TAG))
    assert value=={'version':1,'path':path,'request':TAG,
        'actions':dict.fromkeys(actions,CONFIG['ai_custom_url'] if provider=='local' else PROVIDERS[provider])}

@pytest.mark.parametrize('path',['/','/settings/ai','/external-ai/quiz-builder','/quizzes/../settings.html',
    '/quizzes/bad\\name.html','/certifications/not-id/ai','/certifications/14/ai'])
def test_unsupported_producer_has_no_contract(path):
    assert contract(path,'POST',{},CONFIG,TAG) is None

@pytest.mark.parametrize('target',['file:///C:/a','javascript:bad','ms-settings:apps',
    'https://user:secret@example.invalid/','http://localhost/','http://test.localhost/',
    'http://127.0.0.1/','http://[::1]/','https://example.invalid/\n','https://x.invalid\\@other.invalid/'])
def test_custom_unsafe_target_never_authorized(target):
    assert contract('/review','GET',{},CONFIG|{'ai_provider':'local','ai_custom_url':target},TAG) is None

@pytest.mark.parametrize('tag',['','a'*31,'a'*33,'A'*32,'a'*32+',b',None,1])
def test_tag_fail_closed(tag):assert contract('/review','GET',{},CONFIG,tag) is None

def test_builder_requires_post_and_disabled_helper_not_invented():
    for path in ('/law/create','/study-packs/ai-builder'):
        assert contract(path,'GET',{},CONFIG,TAG) is None
    assert contract('/review','GET',{},CONFIG|{'ai_helper_enabled':False},TAG) is None

def test_header_only_success_html_and_cache_response():
    app=Flask(__name__);install(app,lambda:CONFIG)
    @app.route('/review',methods=['GET','POST'])
    def page():return 'unchanged synthetic body',int(request.args.get('status',200)),{'Content-Type':request.args.get('media','text/html')}
    client=app.test_client()
    for method in ('get','post'):
        response=getattr(client,method)('/review',headers={REQUEST_HEADER:TAG})
        assert response.data==b'unchanged synthetic body'
        assert decoded(response.headers[HEADER])['request']==TAG
    assert HEADER not in client.get('/review').headers
    for query in ('?status=500','?media=application/json','?status=302'):
        assert HEADER not in client.get('/review'+query,headers={REQUEST_HEADER:TAG}).headers
    assert HEADER in client.get('/review?status=304',headers={REQUEST_HEADER:TAG}).headers

def test_config_read_failure_does_not_break_page():
    app=Flask(__name__)
    def fail():raise OSError('private details')
    install(app,fail)
    @app.route('/review')
    def page():return 'still usable'
    response=app.test_client().get('/review',headers={REQUEST_HEADER:TAG})
    assert response.status_code==200 and HEADER not in response.headers

def test_real_certification_uuid_route():
    assert decoded(contract('/certifications/'+'a'*32+'/ai','POST',{},CONFIG,TAG))['actions']=={
        'cert-combined':PROVIDERS['chatgpt'],'cert-manual':PROVIDERS['chatgpt']}
