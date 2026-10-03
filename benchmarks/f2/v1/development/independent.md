# 独立函数
- clamp_int：value/lower/upper 为内置 int（排除 bool），且 lower <= upper。低于下界返回 lower，高于上界返回 upper，闭区间内原样返回 value。域外行为未定义。
- compact_runs：values 为 list[int]，各项为内置 int（排除 bool）。仅保留每段连续相等值的第一项；非相邻重复保留。例如 [1,1,2,1] 返回 [1,2,1]；空列表返回新空列表。不修改输入。
- 两函数相互独立，没有调用边、共享状态或规格定义的组合流程，不要求协作测试。
- 无外部副作用。

