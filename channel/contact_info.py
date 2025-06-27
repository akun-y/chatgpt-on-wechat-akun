#author: akun
#date: 2025-05-02
# -*- coding: utf-8 -*-
from typing import Optional

class ContactInfo(dict):
    name: str
    wxid: str
    display_name: Optional[str]
    real_name: Optional[str]
    remark: Optional[str]
    country: Optional[str]
    province: Optional[str]
    city: Optional[str]
    gender: Optional[str]
    alias: Optional[str]
    avatar: Optional[str]
    corp_id: Optional[str]
    mobile: Optional[str]

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)

    def __setattr__(self, key, value):
        self[key] = value


def make_contact_info(
    name: str,
    wxid: str,
    display_name: Optional[str] = None,
    remark: Optional[str] = None,
    country: Optional[str] = None,
    province: Optional[str] = None,
    city: Optional[str] = None,
    gender: Optional[str] = None,
    alias: Optional[str] = None,
    avatar: Optional[str] = None,
    corp_id: Optional[str] = None,
    real_name: Optional[str] = None,
    mobile: Optional[str] = None,
) -> ContactInfo:
    return ContactInfo(
        name=name,
        wxid=wxid,
        display_name=display_name,
        real_name=real_name or display_name or name,
        remark=remark,
        country=country,
        province=province,
        city=city,
        gender=gender,
        alias=alias,
        avatar=avatar,
        corp_id=corp_id,
        mobile=mobile,
    )