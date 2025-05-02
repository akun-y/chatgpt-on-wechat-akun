#author: akun
#date: 2025-05-02
# -*- coding: utf-8 -*-
from typing import Optional, TypedDict

class ContactInfo(TypedDict):
    name: str
    wxid: str
    display_name: Optional[str]
    remark: Optional[str]
    country: Optional[str]
    province: Optional[str]
    city: Optional[str]
    gender: Optional[str]
    alias: Optional[str]
    avatar: Optional[str]