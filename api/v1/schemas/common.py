# -*- coding: utf-8 -*-
"""
===================================
Common response models
===================================

Responsibilities:
1. Define the shared response models (HealthResponse, ErrorResponse, and so on)
2. Provide a consistent response format
"""

from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field


class RootResponse(BaseModel):
    """API root route response"""
    
    message: str = Field(..., description="API 运行状态消息", json_schema_extra={"example": "Daily Stock Analysis API is running"})
    version: Optional[str] = Field(None, description="API 版本", json_schema_extra={"example": "1.0.0"})
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "message": "Daily Stock Analysis API is running",
            "version": "1.0.0"
        }
    })


class HealthResponse(BaseModel):
    """Health check response"""
    
    status: str = Field(..., description="服务状态", json_schema_extra={"example": "ok"})
    timestamp: Optional[str] = Field(None, description="时间戳")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "ok",
            "timestamp": "2024-01-01T12:00:00"
        }
    })


class ErrorResponse(BaseModel):
    """Error response"""
    
    error: str = Field(..., description="错误类型", json_schema_extra={"example": "validation_error"})
    message: str = Field(..., description="错误详情", json_schema_extra={"example": "请求参数错误"})
    detail: Optional[Any] = Field(None, description="附加错误信息")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": "not_found",
            "message": "资源不存在",
            "detail": None
        }
    })


class SuccessResponse(BaseModel):
    """Generic success response"""
    
    success: bool = Field(True, description="是否成功")
    message: Optional[str] = Field(None, description="成功消息")
    data: Optional[Any] = Field(None, description="响应数据")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "success": True,
            "message": "操作成功",
            "data": None
        }
    })
