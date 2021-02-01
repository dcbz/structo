#include "idalib.h"

struct foo {
	void *vptr;
	_QWORD x;
	_BYTE pad[4];
	_DWORD bar;
	_BYTE padb[80];
};
