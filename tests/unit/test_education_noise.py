"""Education chrome / boilerplate noise filter."""

from __future__ import annotations

from bagel.pipeline.education_noise import filter_education_records, is_education_noise


def test_noise_titles() -> None:
    assert is_education_noise("联系我们")
    assert is_education_noise("网站地图")
    assert is_education_noise("网站声明")
    assert is_education_noise("版权声明")
    assert is_education_noise("隐私政策")
    assert is_education_noise("English")
    assert is_education_noise("首页")
    assert is_education_noise("友情链接")
    assert is_education_noise("关于我们")
    assert not is_education_noise("教育部关于印发义务教育课程标准的通知")
    assert not is_education_noise("全国高等学校名单")


def test_noise_urls() -> None:
    assert is_education_noise(
        "网站声明",
        "https://www.moe.gov.cn/jyb_sy/s3634/201005/t20100504_87292.html",
    )
    assert is_education_noise(
        "任意标题",
        "https://www.moe.gov.cn/jyb_sy/s3635/201611/t20161129_290403.html",
    )
    assert is_education_noise(
        "任意标题",
        "https://www.moe.gov.cn/jyb_sy/s3636/202404/t20240411_1125026.html",
    )
    assert not is_education_noise(
        "中华人民共和国主席令",
        "https://www.moe.gov.cn/jyb_xxgk/moe_1777/moe_1778/202409/t20240913_1150861.html",
    )


def test_filter_records() -> None:
    from bagel.collectors.education import EducationRecord

    rows = [
        EducationRecord(
            title="联系我们",
            url="https://www.moe.gov.cn/jyb_sy/s3635/x.html",
            summary="",
            authors="教育部",
            published_at=None,
            source_name="t",
            external_id="a",
        ),
        EducationRecord(
            title="教育部印发通知推进基础教育扩优提质",
            url="https://www.moe.gov.cn/jyb_xxgk/202601/t20260101_1.html",
            summary="",
            authors="教育部",
            published_at=None,
            source_name="t",
            external_id="b",
        ),
    ]
    kept = filter_education_records(rows)
    assert len(kept) == 1
    assert "扩优提质" in kept[0].title
