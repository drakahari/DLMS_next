"""Optional editable starting points; never a credential or an approval.

Sources checked 2026-10-07. No network calls at runtime. Personal dates, versions,
issuer acceptance and reporting-year anchors must be supplied by the user.
"""
CHECKED = '2026-10-07'
PRESETS = {
    'cism-2026': dict(label='CISM — 2026 CPE policy', required=120, unit='CPE',
        policy='https://www.isaca.org/-/media/files/isacadp/project/isaca/certification/general/cpe_policy.pdf',
        tracking=dict(version='CISM · 2026 CPE policy', route='Continuing professional education',
            annual_kind='minimum', annual_amount=20, year_basis='calendar',
            categories=[dict(name='CISM exam content', minimum=90, cap=None),dict(name='Other professional development',minimum=None,cap=30)],
            conditions='Verify your three-year dates, activity-specific caps, relevance, fees, ethics and audit obligations. Initial certification-year credit has a special reporting rule; record any reporting-date exception explicitly.')),
    'cissp-v7': dict(label='CISSP — member policy v7', required=120, unit='CPE',
        policy='https://www.isc2.org/policies-procedures/member-policies',
        tracking=dict(version='CISSP · member policy v7',route='Continuing professional education',
            annual_kind='pacing',annual_amount=40,year_basis='unknown',
            categories=[dict(name='Group A',minimum=90,cap=None),dict(name='Group B',minimum=None,cap=30)],
            conditions='40 per year is suggested pacing, not a mandatory annual minimum. Verify cycle/reporting dates, activity-specific rules, maintenance fees, ethics and audit obligations.')),
    'lpic-exams': dict(label='LPIC — current-exam renewal route',required='',unit='credits',
        policy='https://www.lpi.org/our-certifications/renewal/',
        tracking=dict(version='LPIC — specify level and current exam version',route='Retake required current exams',
            annual_kind='none',year_basis='unknown',
            conditions='Exam renewal normally keeps the designation active for five years. Confirm the required current exams for your level. Training-credit totals do not satisfy this route. Record the issuer-confirmed expiration yourself; no date is calculated.')),
    'lpic-membership': dict(label='LPIC — optional LPI membership / PDU route',required=60,unit='PDU',
        policy='https://www.lpi.org/member/pdu-procedures-and-policies/',
        tracking=dict(version='LPIC — specify level; LPI membership policy',route='LPI membership / three-year PDU cycle',
            annual_kind='unknown',year_basis='unknown',
            categories=[dict(name='Education',minimum=30,cap=50),dict(name='Community',minimum=None,cap=20),dict(name='Experience',minimum=None,cap=30)],
            conditions='Membership term, certification status and the PDU cycle are different: enter the actual membership activation/reporting dates and issuer-recorded credential expiration. The 60 PDUs do not establish a new three-year certification expiration. Verify dues, membership acceptance, relevance and activity-specific caps. The membership FAQ explicitly says no 20-PDU annual minimum, while the renewal page still says 20 annually; confirm the applicable rule with LPI. The FAQ distinguishes 20 recent PDUs for inactive holders applying for membership. No automatic carry-forward.')),
    'peoplecert-custom': dict(label='PeopleCert — verify credential version and route',required='',unit='CPD',
        policy='https://www.peoplecert.org/help-and-support/FAQ',
        tracking=dict(version='',route='',annual_kind='unknown',year_basis='unknown',
            conditions='Incomplete starting point: confirm exact credential version and route. Plus-membership CPD and examination renewal differ. Do not apply an ITIL 4 rule to ITIL v3 or another product. Enter verified requirements and your dates before using progress estimates.')),
}


def values(key):
    from copy import deepcopy
    if key not in PRESETS:raise ValueError('Choose an available preset, or enter custom rules.')
    item=deepcopy(PRESETS[key]);item.pop('label')
    item['tracking'].update(checked=CHECKED,verification='unverified',requirement_known=item['required']!='')
    return item
