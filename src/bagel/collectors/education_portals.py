"""Known K12 / 考研 portal list pages — durable alternative to keyword watch."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EducationPortal:
    key: str
    label: str
    kind: str  # k12 | kaoyan
    aliases: tuple[str, ...]
    list_urls: tuple[str, ...]
    institution: str
    facet: str
    note: str = ""


# 考研：直连高校研招网公告列表（不依赖 RSSHub / 研招网标题命中）
KAOYAN_PORTALS: tuple[EducationPortal, ...] = (
    EducationPortal(
        key="scu",
        label="川大研招 · 硕士公告",
        kind="kaoyan",
        aliases=("川大", "四川大学", "scu"),
        list_urls=("https://yz.scu.edu.cn/zsxx/newslist/ss/gg",),
        institution="四川大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="sjtu",
        label="上交研招 · 硕士招生",
        kind="kaoyan",
        aliases=("上交", "上海交大", "上海交通大学", "sjtu"),
        list_urls=(
            "https://yzb.sjtu.edu.cn/zkxx/sszs",
            "https://yzb.sjtu.edu.cn/zsjz/sszs",
            "https://yzb.sjtu.edu.cn/",
        ),
        institution="上海交通大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="pku",
        label="北大研招 · 硕士简章",
        kind="kaoyan",
        aliases=("北大", "北京大学", "pku", "peking"),
        list_urls=(
            "https://admission.pku.edu.cn/zsxx/sszs/zsjz/index.htm",
            "https://admission.pku.edu.cn/zsxx/sszs/ptzk/index.htm",
        ),
        institution="北京大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="tsinghua",
        label="清华研招",
        kind="kaoyan",
        aliases=("清华", "清华大学", "tsinghua", "thu"),
        list_urls=("https://yz.tsinghua.edu.cn/",),
        institution="清华大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="fudan",
        label="复旦研招",
        kind="kaoyan",
        aliases=("复旦", "复旦大学", "fudan"),
        list_urls=("https://gsao.fudan.edu.cn/", "https://www.gsao.fudan.edu.cn/"),
        institution="复旦大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="nju",
        label="南大研招",
        kind="kaoyan",
        aliases=("南大", "南京大学", "nju"),
        list_urls=("https://yz.nju.edu.cn/main.htm", "https://yz.nju.edu.cn/"),
        institution="南京大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="whu",
        label="武大研招",
        kind="kaoyan",
        aliases=("武大", "武汉大学", "whu"),
        list_urls=("https://gs.whu.edu.cn/", "https://www.gs.whu.edu.cn/zsxx.htm"),
        institution="武汉大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="uestc",
        label="电子科大研招",
        kind="kaoyan",
        aliases=("成电", "电子科大", "电子科技大学", "uestc"),
        list_urls=("https://yz.uestc.edu.cn/", "https://yz.uestc.edu.cn/zsxx/sszs.htm"),
        institution="电子科技大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="hit",
        label="哈工大研招",
        kind="kaoyan",
        aliases=("哈工大", "哈尔滨工业大学", "hit"),
        list_urls=("https://yz.hit.edu.cn/",),
        institution="哈尔滨工业大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="xjtu",
        label="西交研招",
        kind="kaoyan",
        aliases=("西交", "西安交大", "西安交通大学", "xjtu"),
        list_urls=("https://yz.xjtu.edu.cn/",),
        institution="西安交通大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="hust",
        label="华科研招",
        kind="kaoyan",
        aliases=("华科", "华中科技大学", "hust"),
        list_urls=("https://gs.hust.edu.cn/",),
        institution="华中科技大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="tongji",
        label="同济研招",
        kind="kaoyan",
        aliases=("同济", "同济大学", "tongji"),
        list_urls=("https://yz.tongji.edu.cn/",),
        institution="同济大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="bit",
        label="北理工研招",
        kind="kaoyan",
        aliases=("北理", "北理工", "北京理工大学", "bit"),
        list_urls=("https://grd.bit.edu.cn/",),
        institution="北京理工大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="buaa",
        label="北航研招",
        kind="kaoyan",
        aliases=("北航", "北京航空航天大学", "buaa"),
        list_urls=("https://yzb.buaa.edu.cn/",),
        institution="北京航空航天大学",
        facet="prospectus",
    ),
    EducationPortal(
        key="ruc",
        label="人大研招",
        kind="kaoyan",
        aliases=("人大", "中国人民大学", "ruc"),
        list_urls=("https://pgs.ruc.edu.cn/",),
        institution="中国人民大学",
        facet="prospectus",
    ),
)

# K12：省市教育厅/教委列表页（城市映射到省级厅站点，稳定可采）
K12_PORTALS: tuple[EducationPortal, ...] = (
    EducationPortal(
        key="sichuan",
        label="四川省教育厅 · 通知公告",
        kind="k12",
        aliases=("四川", "四川省", "成都", "成都市", "川"),
        list_urls=(
            "https://edu.sc.gov.cn/scedu/c100495/xwzx_list.shtml",
            "https://edu.sc.gov.cn/scedu/c100494/xwzx_list.shtml",
        ),
        institution="四川省教育厅",
        facet="city",
        note="成都等四川地市默认订阅省厅通知/要闻",
    ),
    EducationPortal(
        key="beijing",
        label="北京教委 · 通知",
        kind="k12",
        aliases=("北京", "北京市", "京"),
        list_urls=("https://jw.beijing.gov.cn/",),
        institution="北京市教委",
        facet="city",
    ),
    EducationPortal(
        key="shanghai",
        label="上海教委",
        kind="k12",
        aliases=("上海", "上海市", "沪"),
        list_urls=("https://edu.sh.gov.cn/", "https://www.shanghai.gov.cn/nw12344/index.html"),
        institution="上海市教委",
        facet="city",
    ),
    EducationPortal(
        key="guangdong",
        label="广东省教育厅",
        kind="k12",
        aliases=("广东", "广东省", "广州", "广州市", "深圳", "深圳市", "粤"),
        list_urls=(
            "https://edu.gd.gov.cn/zxzx/tzgg/",
            "https://edu.gd.gov.cn/",
        ),
        institution="广东省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="zhejiang",
        label="浙江省教育厅",
        kind="k12",
        aliases=("浙江", "浙江省", "杭州", "杭州市", "浙"),
        list_urls=("https://jyt.zj.gov.cn/",),
        institution="浙江省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="jiangsu",
        label="江苏省教育厅",
        kind="k12",
        aliases=("江苏", "江苏省", "南京", "南京市", "苏"),
        list_urls=("https://jyt.jiangsu.gov.cn/",),
        institution="江苏省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="hubei",
        label="湖北省教育厅",
        kind="k12",
        aliases=("湖北", "湖北省", "武汉", "武汉市", "鄂"),
        list_urls=("https://jyt.hubei.gov.cn/",),
        institution="湖北省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="shaanxi",
        label="陕西省教育厅",
        kind="k12",
        aliases=("陕西", "陕西省", "西安", "西安市", "陕"),
        list_urls=("https://jyt.shaanxi.gov.cn/",),
        institution="陕西省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="henan",
        label="河南省教育厅",
        kind="k12",
        aliases=("河南", "河南省", "郑州", "郑州市", "豫"),
        list_urls=("https://jyt.henan.gov.cn/",),
        institution="河南省教育厅",
        facet="city",
    ),
    EducationPortal(
        key="shandong",
        label="山东省教育厅",
        kind="k12",
        aliases=("山东", "山东省", "济南", "青岛", "鲁"),
        list_urls=("http://edu.shandong.gov.cn/",),
        institution="山东省教育厅",
        facet="city",
    ),
)


def _norm(text: str) -> str:
    return (
        (text or "")
        .strip()
        .lower()
        .replace("大学", "")
        .replace("市", "")
        .replace("省", "")
        .replace(" ", "")
    )


def resolve_portal(query: str, *, kind: str) -> EducationPortal | None:
    """Match city/school query to a known portal."""
    pool = K12_PORTALS if kind == "k12" else KAOYAN_PORTALS
    q = (query or "").strip()
    if not q:
        return None
    qn = _norm(q)
    exact: list[EducationPortal] = []
    fuzzy: list[EducationPortal] = []
    for p in pool:
        alias_set = {_norm(a) for a in p.aliases} | {_norm(p.institution), _norm(p.label), p.key}
        if q in p.aliases or q == p.institution or qn in alias_set:
            exact.append(p)
            continue
        if any(qn and (qn in a or a in qn) for a in alias_set if a):
            fuzzy.append(p)
    hits = exact or fuzzy
    return hits[0] if hits else None


def list_portal_labels(kind: str) -> list[str]:
    pool = K12_PORTALS if kind == "k12" else KAOYAN_PORTALS
    return [p.aliases[0] for p in pool]
