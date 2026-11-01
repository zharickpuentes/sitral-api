"""Capa de APLICACIÓN: casos de uso.

Cada servicio recibe sus dependencias (repositorios y adaptadores) por
CONSTRUCTOR, tipadas con los puertos del dominio. No conoce FastAPI,
SQLAlchemy, httpx ni DuckDB: por eso se prueba con objetos Mock.
"""
